# -------------------------------------------------------------------------------
# Name:        Constraints and Opportunities Model
# Purpose:     Adds the constraints and opportunities model to the BRAT capacity output
#
# Author:      Sara Bangen
#
# Created:     06/2018
# Copyright:   (c) Bangen 2018
# Licence:     <your licence>
# -------------------------------------------------------------------------------

import arcpy
import sys
import os
import projectxml
from SupportingFunctions import make_layer, make_folder, find_available_num_prefix, find_relative_path, write_xml_element_with_path
import XMLBuilder
reload(XMLBuilder)
XMLBuilder = XMLBuilder.XMLBuilder


def main(proj_path, in_network, out_name, surveyed_dams=None, conservation_areas=None, conservation_easements=None):
    """
    For each stream segment, assigns a conservation and restoration class
    :param proj_path: The file path to the BRAT project folder
    :param in_network:  The input Combined Capacity Network
    :param out_name: The output name for the Conservation Restoration Model
    :param surveyed_dams: The dams shapefile
    :param conservation_areas: The conservation areas shapefile
    :param conservation_easements: The conservation easements shapefile
    :return:
    """
    arcpy.env.overwriteOutput = True

    out_network = os.path.dirname(in_network) + "/" + out_name + ".shp"
    arcpy.CopyFeatures_management(in_network, out_network)

    # check for oPBRC fields and delete if exists
    old_fields = [f.name for f in arcpy.ListFields(out_network)]
    cons_rest_fields = ["oPBRC_UI", "oPBRC_UD", "oPBRC_CR", "DamStrat", "ObsDam", "ConsRest", "ConsEase"]
    for f in cons_rest_fields:
        if f in old_fields:
            arcpy.DeleteField_management(out_network, f)

    # add all new fields
    arcpy.AddField_management(out_network, "oPBRC_UI", "TEXT", "", "", 30)
    arcpy.AddField_management(out_network, "oPBRC_UD", "TEXT", "", "", 30)
    arcpy.AddField_management(out_network, "oPBRC_CR", "TEXT", "", "", 40)
    arcpy.AddField_management(out_network, "DamStrat", "TEXT", "", "", 60)
    arcpy.AddField_management(out_network, "ObsDam", "TEXT", "", "", 10)
    arcpy.AddField_management(out_network, "ConsArea", "TEXT", "", "", 10)
    arcpy.AddField_management(out_network, "ConsEase", "TEXT", "", "", 10)

    # use old historic capacity field names if new ones not in combined capacity output
    if 'oVC_PT' in old_fields:
        ovc_hpe = 'oVC_PT'
    else:
        ovc_hpe = 'oVC_Hpe'

    if 'oCC_PT' in old_fields:
        occ_hpe = 'oCC_PT'
    else:
        occ_hpe = 'oCC_HPE'

    fields = ['oPBRC_UI', 'oPBRC_UD', 'oPBRC_CR', ovc_hpe, 'oVC_EX', occ_hpe, 'oCC_EX', 'iGeo_Slope', 'mCC_HisDep',
              'iPC_VLowLU', 'iPC_HighLU', 'oPC_Dist', 'iPC_LU', 'iHyd_SPLow', 'iHyd_SP2', 'DamStrat', 'iPC_RoadX',
              'iPC_Canal', 'ObsDam', 'ConsArea', 'ConsEase']

    for field in fields:
        if field not in [f.name for f in arcpy.ListFields(out_network)]:
            arcpy.AddWarning('Missing {} Field!'.format(field))

    # add arbitrarily large value to avoid error
    if 'iPC_Canal' not in old_fields:
        arcpy.AddField_management(out_network, "iPC_Canal", "DOUBLE")
        arcpy.CalculateField_management(out_network, 'iPC_Canal', """500000""", "PYTHON")

    # 'oPBRC_UI' (Areas beavers can build dams, but could be undesireable impacts)
    # arcpy.AddMessage(fields)
    # field_check = [f.name for f in arcpy.ListFields(out_network)]
    # arcpy.AddMessage("--------------------")
    # arcpy.AddMessage(field_check)
    with arcpy.da.UpdateCursor(out_network, fields) as cursor:
        for row in cursor:

            occ_ex = row[6]
            opc_dist = row[11]
            ipc_lu = row[12]
            ipc_canal = row[17]
            
            if occ_ex <= 0:
                # if capacity is none risk is negligible
                row[0] = "Negligible Risk"
            elif ipc_canal <= 20:
                # if canals are within 20 meters (usually means canal is on the reach)
                row[0] = "Major Risk"
            else:
                # if infrastructure within 30 m or land use is high
                # if capacity is frequent or pervasive risk is considerable
                # if capaicty is rare or ocassional risk is some
                if opc_dist <= 30 or ipc_lu >= 0.66:
                    if occ_ex >= 5.0:
                        row[0] = "Major Risk"
                    else:
                        row[0] = "Considerable Risk"
                # if infrastructure within 30 to 100 m
                # if capacity is frequent or pervasive risk is some
                # if capacity is rare or ocassional risk is minor
                elif opc_dist <= 100:
                    if occ_ex >= 5.0:
                        row[0] = "Considerable Risk"
                    else:
                        row[0] = "Minor Risk"
                # if infrastructure within 100 to 300 m or land use is 0.33 to 0.66 risk is minor
                elif opc_dist <= 300 or ipc_lu >= 0.33:
                    row[0] = "Minor Risk"
                else:
                    row[0] = "Negligible Risk"

            cursor.updateRow(row)

    # 'oPBRC_UD' (Areas beavers can't build dams and why)
    with arcpy.da.UpdateCursor(out_network, fields) as cursor:
        for row in cursor:

            ovc_hpe = row[3]
            ovc_ex = row[4]
            occ_ex = row[6]
            slope = row[7]
            landuse = row[12]
            splow = row[13]
            sp2 = row[14]

            # First deal with vegetation limitations
            # Find places historically veg limited first ('oVC_HPE' None)
            if ovc_hpe <= 0:
                # 'oVC_EX' Occasional, Frequent, or Pervasive (some areas have oVC_EX > oVC_HPE)
                if ovc_ex > 0:
                    row[1] = 'Potential Reservoir or Landuse Conversion'
                else:    
                    row[1] = 'Naturally Vegetation Limited'    
            # 'iGeo_Slope' > 23%
            elif slope > 0.23:
                row[1] = 'Slope Limited'
            # 'oCC_EX' None (Primary focus of this layer is the places that can't support dams now... so why?)
            elif occ_ex <= 0:
                if landuse > 0.3:
                    row[1] = "Anthropogenically Limited"
                elif splow >= 190 or sp2 >= 2400:
                    row[1] = "Stream Power Limited"
                else:
                    row[1] = "Stream Size Limited"
            else:
                row[1] = 'Dam Building Possible'

            cursor.updateRow(row)

    # 'oPBRC_CR' (Conservation & Restoration Opportunties)
    with arcpy.da.UpdateCursor(out_network, fields) as cursor:
        for row in cursor:
            # 'oPBRC_UI' Negligible Risk or Minor Risk
            opbrc_ui = row[0]
            occ_hpe = row[5]
            occ_ex = row[6]
            mcc_his_dep = row[8]
            ipc_vlow_lu = row[9]
            ipc_high_lu = row[10]
            if opbrc_ui == 'Negligible Risk' or opbrc_ui == 'Minor Risk':
                # 'oCC_EX' Frequent or Pervasive
                # 'mcc_his_dep' <= 3
                if occ_ex >= 5 and mcc_his_dep <= 3:
                    row[2] = 'Easiest - Low-Hanging Fruit'
                # 'oCC_EX' Occasional, Frequent, or Pervasive
                # 'oCC_HPE' Frequent or Pervasive
                # 'mcc_his_dep' <= 3
                # 'ipc_vlow_lu'(i.e., Natural) > 75
                # 'ipc_high_lu' (i.e., Developed) < 10
                elif occ_ex > 1 and mcc_his_dep <= 3 and occ_hpe >= 5 and ipc_vlow_lu > 75 and ipc_high_lu < 10:
                    row[2] = 'Straight Forward - Quick Return'
                # 'oCC_EX' Rare or Occasional
                # 'oCC_HPE' Frequent or Pervasive
                # 'ipc_vlow_lu'(i.e., Natural) > 75
                # 'ipc_high_lu' (i.e., Developed) < 10
                elif occ_hpe >= 5 and occ_ex > 0 and ipc_vlow_lu > 75 and ipc_high_lu < 10:
                    row[2] = 'Strategic - Long-Term Investment'
                else:
                    row[2] = 'NA'
            else:
                row[2] = 'NA'
            cursor.updateRow(row)

    if conservation_areas is not None and surveyed_dams is not None:
        # beaver dam management strategies (derived from TNC project)
        with arcpy.da.UpdateCursor(out_network, ["ObsDam", "ConsArea", "ConsEase"]) as cursor:
            for row in cursor:
                row[0] = "No"
                row[1] = "No"
                row[2] = "No"
                cursor.updateRow(row)

        network_lyr = arcpy.MakeFeatureLayer_management(out_network, "network_lyr")

        dams = os.path.join(proj_path, 'tmp_snapped_dams.shp')
        arcpy.CopyFeatures_management(surveyed_dams, dams)
        arcpy.Snap_edit(dams, [[out_network, 'EDGE', '60 Meters']])
        arcpy.SelectLayerByLocation_management(network_lyr, "INTERSECT", dams, '', "NEW_SELECTION")
        with arcpy.da.UpdateCursor(network_lyr, ["ObsDam"]) as cursor:
            for row in cursor:
                row[0] = "Yes"
                cursor.updateRow(row)

        arcpy.SelectLayerByLocation_management(network_lyr, "INTERSECT", conservation_areas, '', "NEW_SELECTION")
        with arcpy.da.UpdateCursor(network_lyr, ["ConsArea"]) as cursor:
            for row in cursor:
                row[0] = "Yes"
                cursor.updateRow(row)

        arcpy.SelectLayerByLocation_management(network_lyr, "INTERSECT", conservation_easements, '', "NEW_SELECTION")
        with arcpy.da.UpdateCursor(network_lyr, ["ConsEase"]) as cursor:
            for row in cursor:
                row[0] = "Yes"
                cursor.updateRow(row)

        with arcpy.da.UpdateCursor(out_network, fields) as cursor:
            for row in cursor:
                # 'oPBRC_UI' Negligible Risk or Minor Risk
                opbrc_ui = row[0]
                hist_veg = row[3]
                curr_veg = row[4]
                curr_dams = row[6]
                infrastructure_dist = row[11]
                landuse = row[12]
                obs_dams = row[18]
                protected = row[19]
                easement = row[20]

                hist_veg_departure = hist_veg - curr_veg
                urban = landuse > 0.66
                ag = 0.33 < landuse <= 0.66
                no_urban = not urban
                no_ag = not ag

                # default category is 'Other'
                row[15] = 'Other'

                if curr_dams >= 5:
                    if no_urban:
                        if hist_veg_departure >= 4:
                            row[15] = "3a. Vegetation restoration first-priority"
                        else:
                            row[15] = "3. High restoration potential"

                if curr_dams >= 20 and protected == 'Yes':
                    row[15] = "2. Highest restoration potential - translocation"

                if curr_dams >= 20 and easement == 'Yes':
                    row[15] = "2. Highest restoration potential - translocation"

                if 1 <= curr_dams < 5 and no_urban:
                    if hist_veg_departure >= 4:
                        row[15] = "4a. Vegetation restoration first-priority"
                    else:
                        row[15] = "4. Medium-low restoration potential"

                if curr_dams >= 1 and infrastructure_dist <= 30:
                    row[15] = "5. Restoration with infrastructure modification"

                if curr_dams >= 1 and urban:
                    row[15] = "6. Restoration with urban or agricultural modification"

                if curr_dams >= 1 and ag:
                    row[15] = "6. Restoration with urban or agricultural modification"

                if obs_dams == 'Yes' and no_urban and no_ag:
                    row[15] = "1. Beaver conservation"

                cursor.updateRow(row)

        arcpy.Delete_management(dams)

    else:  # remove strategies map fields if not running this part of the model
        arcpy.DeleteField_management(out_network, "DamStrat")
        arcpy.DeleteField_management(out_network, "ObsDam")
        arcpy.DeleteField_management(out_network, "ConsRest")
        arcpy.DeleteField_management(out_network, "ConsEase")
        
    make_layers(out_network)

    write_xml(in_network, out_network)

    return out_network


def make_layers(out_network):
    """
    Writes the layers
    :param out_network: The output network, which we want to make into a layer
    :return:
    """
    arcpy.AddMessage("Making layers...")
    analyses_folder = os.path.dirname(out_network)
    output_folder = make_folder(analyses_folder, find_available_num_prefix(analyses_folder) + "_Management")

    trib_code_folder = os.path.dirname(os.path.abspath(__file__))
    symbology_folder = os.path.join(trib_code_folder, 'BRATSymbology')
    
    strategy_map_symbology = os.path.join(symbology_folder, "StrategiestoPromoteDamBuilding.lyr")
    limitations_dams_symbology = os.path.join(symbology_folder, "UnsuitableorLimitedDamBuildingOpportunities.lyr")
    undesirable_dams_symbology = os.path.join(symbology_folder, "RiskofUndesirableDams.lyr")
    conservation_restoration_symbology = os.path.join(symbology_folder, "BeaverDamConstraintsandOpportunities.lyr")
    
    make_layer(output_folder, out_network, "Unsuitable or Limited Dam Building Opportunities",
               limitations_dams_symbology, is_raster=False, symbology_field='oPBRC_UD')
    make_layer(output_folder, out_network, "Risk of Undesirable Dams",
               undesirable_dams_symbology, is_raster=False, symbology_field='oPBRC_UI')
    make_layer(output_folder, out_network, "Beaver Dam Constraints and Opportunities",
               conservation_restoration_symbology, is_raster=False, symbology_field='oPBRC_CR')

    # only try making strategies map layer if 'DamStrat' in fields
    fields = [f.name for f in arcpy.ListFields(out_network)]
    if 'DamStrat' in fields:
        make_layer(output_folder, out_network, "Strategies to Promote Dam Building",
                   strategy_map_symbology, is_raster=False, symbology_field='DamStrat')


def write_xml(in_network, out_network):
    """
    Writes relevant data to the project's XML document
    :param in_network: The input Combined Capacity Network
    :param out_network: The new Conservation Restoration Network
    :return:
    """
    proj_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(in_network))))

    xml_file_path = os.path.join(proj_path, "project.rs.xml")

    if not os.path.exists(xml_file_path):
        arcpy.AddWarning("XML file not found. Could not update XML file")
        return

    xml_file = XMLBuilder(xml_file_path)
    in_network_rel_path = find_relative_path(in_network, proj_path)

    path_element = xml_file.find_by_text(in_network_rel_path)
    analysis_element = xml_file.find_element_parent(xml_file.find_element_parent(path_element))

    write_xml_element_with_path(xml_file, analysis_element, "Vector",
                                "BRAT Conservation and Restoration Output", out_network, proj_path)

    xml_file.write()


if __name__ == '__main__':
    main(sys.argv[1],
         sys.argv[2],
         sys.argv[3],
         sys.argv[4],
         sys.argv[5],
         sys.argv[6])
