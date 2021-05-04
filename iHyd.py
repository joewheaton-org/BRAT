# -------------------------------------------------------------------------------
# Name:        iHYD
# Purpose:     Adds the hydrologic attributes to the BRAT input table
#
# Author:      Jordan
#
# Created:     09/2016
# Copyright:   (c) Jordan 2016
# Licence:     <your licence>
# -------------------------------------------------------------------------------

import arcpy
import numpy as np
import os
import sys
from SupportingFunctions import make_layer, make_folder, find_available_num_prefix, find_relative_path
import XMLBuilder
reload(XMLBuilder)
XMLBuilder = XMLBuilder.XMLBuilder


def main(in_network, region, q_low_eqtn, q2_eqtn):
    """
    The main function, adds all hydrologic attributes to the BRAT table
    :param in_network: The input BRAT table to add hydrologic values to
    :param region: The optional region code to identify an already existing equation
    :param q_low_eqtn: The Qlow equation to be calculated
    :param q2_eqtn: The Q2 equation to be calculated
    :return:
    """
    if region is None or region == "None":
        region = 0
    else:
        region = int(region)
    if q_low_eqtn == "None":
        q_low_eqtn = None
    if q2_eqtn == "None":
        q2_eqtn = None

    scratch = 'in_memory'

    arcpy.env.overwriteOutput = True

    # create segid array for joining output to input network
    segid_np = arcpy.da.FeatureClassToNumPyArray(in_network, "ReachID")
    segid = np.asarray(segid_np, np.int64)

    # create array for input network drainage area ("iGeo_DA")
    da_array = arcpy.da.FeatureClassToNumPyArray(in_network, "iGeo_DA")
    da = np.asarray(da_array, np.float32)

    # convert drainage area (in square kilometers) to square miles
    # note: this assumes that streamflow equations are in US customary units (e.g., inches, feet)

    # TODO Why do these get need to be initialized? Is it necessary to set them to zero first?
    DAsqm = np.zeros_like(da)
    DAsqm = da * 0.3861021585424458

    # create Qlow and Q2
    q_low = np.zeros_like(da)
    q2 = np.zeros_like(da)

    arcpy.AddMessage("Adding Qlow and Q2 to network...")

    # --regional curve equations for Qlow (baseflow) and Q2 (annual peak streamflow)--
    # # # Add in regional curve equations here # # #
    if q_low_eqtn is not None:
        arcpy.AddMessage("Evaluating qlow...")
        q_low = eval(q_low_eqtn)
    elif region == 101:  # example 1 (box elder county)
        q_low = 0.019875 * (DAsqm ** 0.6634) * (10 ** (0.6068 * 2.04))
    elif region == 102:  # example 2 (upper green generic)
        q_low = 4.2758 * (DAsqm ** 0.299)
    elif region == 24:  # oregon region 5
        q_low = 0.000133 * (DAsqm ** 1.05) * (15.3 ** 2.1)
    else:
        q_low = (DAsqm ** 0.2098) + 1

    if q2_eqtn is not None:
        arcpy.AddMessage("Evaluating q2...")
        q2 = eval(q2_eqtn)
    elif region == 101:  # example 1 (box elder county)
        q2 = 14.5 * DAsqm ** 0.328
    elif region == 102:  # example 2 (upper green generic)
        q2 = 22.2 * (DAsqm ** 0.608) * ((42 - 40) ** 0.1)
    elif region == 24:  # oregon region 5
        q2 = 0.000258 * (DAsqm ** 0.893) * (15.3 ** 3.15)
    else:
        q2 = 14.7 * (DAsqm ** 0.815)

    # save segid, Qlow, Q2 as single table
    columns = np.column_stack((segid, q_low, q2))
    tmp_table = os.path.dirname(in_network) + "/ihyd_Q_Table.txt"
    np.savetxt(tmp_table, columns, delimiter=",", header="ReachID, iHyd_QLow, iHyd_Q2", comments="")
    ihyd_table = scratch + "/ihyd_table"
    arcpy.CopyRows_management(tmp_table, ihyd_table)

    # join Qlow and Q2 output to the flowline network
    # create empty dictionary to hold input table field values
    tbl_dict = {}
    # add values to dictionary
    with arcpy.da.SearchCursor(ihyd_table, ['ReachID', "iHyd_QLow", "iHyd_Q2"]) as cursor:
        for row in cursor:
            tbl_dict[row[0]] = [row[1], row[2]]
    # check for and delete if output fields already included in flowline network
    remove_existing_output(in_network)
    # populate flowline network out field
    arcpy.AddField_management(in_network, "iHyd_QLow", 'DOUBLE')
    arcpy.AddField_management(in_network, "iHyd_Q2", 'DOUBLE')
    with arcpy.da.UpdateCursor(in_network, ['ReachID', "iHyd_QLow", "iHyd_Q2"]) as cursor:
        for row in cursor:
            try:
                a_key = row[0]
                row[1] = tbl_dict[a_key][0]
                row[2] = tbl_dict[a_key][1]
                cursor.updateRow(row)
            # TODO There should not be any blank exceptions. What error is this supposed to throw?
            except:
                pass
    tbl_dict.clear()

    # delete temporary table
    arcpy.Delete_management(tmp_table)

    # check that Q2 is greater than Qlow
    # if not, re-calculate Q2 as Qlow + 0.001
    with arcpy.da.UpdateCursor(in_network, ["iHyd_QLow", "iHyd_Q2"]) as cursor:
        for row in cursor:
            if row[1] < row[0]:
                row[1] = row[0] + 0.001
            else:
                pass
            cursor.updateRow(row)

    arcpy.AddMessage("Adding stream power to network...")

    # calculate Qlow and Q2 stream power

    # where stream power =
    # density of water (1000 kg/m3) * acceleration due to gravity (9.80665 m/s2) * discharge (m3/s) * channel slope

    # note: we assume that discharge ("iHyd_QLow", "iHyd_Q2") was calculated in cubic feet per second
    # and handle conversion to cubic meters per second (e.g., "iHyd_QLow" * 0.028316846592

    arcpy.AddField_management(in_network, "iHyd_SPLow", "DOUBLE")
    arcpy.AddField_management(in_network, "iHyd_SP2", "DOUBLE")
    with arcpy.da.UpdateCursor(in_network, ["iGeo_Slope", "iHyd_QLow", "iHyd_SPLow", "iHyd_Q2", "iHyd_SP2"]) as cursor:
        for row in cursor:
            if row[0] < 0.001:
                slope = 0.001
            else:
                slope = row[0]
            row[2] = (1000 * 9.80665) * slope * (row[1] * 0.028316846592)
            row[4] = (1000 * 9.80665) * slope * (row[3] * 0.028316846592)
            cursor.updateRow(row)

    make_layers(in_network)

    # add equations to XML
    # if q_low_eqtn is not None and q2_eqtn is not None and region is not None:
    #    xml_add_equations(in_network, region, q_low_eqtn, q2_eqtn)


def remove_existing_output(in_network):
    """
    Checks if the hydrologic fields already exist, and if they do, deletes them for a clean slate
    :param in_network: The input BRAT table network
    :return:
    """
    if "iHyd_QLow" in [field.name for field in arcpy.ListFields(in_network)]:    
        arcpy.DeleteField_management(in_network, "iHyd_Qlow")
    if "iHyd_Q2" in [field.name for field in arcpy.ListFields(in_network)]:
        arcpy.DeleteField_management(in_network, "iHyd_Q2")
    if "iHyd_SPLow" in [field.name for field in arcpy.ListFields(in_network)]:
        arcpy.DeleteField_management(in_network, "iHyd_SPLow")
    if "iHyd_SP2" in [field.name for field in arcpy.ListFields(in_network)]:
        arcpy.DeleteField_management(in_network, "iHyd_SP2")


def make_layers(input_network):
    """
    Makes the layers for the modified output
    :param input_network: The path to the network that we'll make a layer from
    :return:
    """
    arcpy.AddMessage("Making layers...")
    intermediates_folder = os.path.dirname(input_network)
    hydrology_folder_name = find_available_num_prefix(intermediates_folder) + "_Hydrology"
    hydrology_folder = make_folder(intermediates_folder, hydrology_folder_name)

    trib_code_folder = os.path.dirname(os.path.abspath(__file__))
    symbology_folder = os.path.join(trib_code_folder, 'BRATSymbology')

    highflow_symbology = os.path.join(symbology_folder, "HighflowStreamPower.lyr")
    baseflow_symbology = os.path.join(symbology_folder, "BaseflowStreamPower.lyr")

    make_layer(hydrology_folder, input_network, "Highflow Stream Power", highflow_symbology, is_raster=False)
    make_layer(hydrology_folder, input_network, "Baseflow Stream Power", baseflow_symbology, is_raster=False)


def xml_add_equations(in_network, region, q_low_eqtn, q2_eqtn):
    """
    Adds the equation strings into the project's XML document
    :param in_network: The input BRAT table to add hydrologic values to
    :param region: The optional region code to identify an already existing equation
    :param q_low_eqtn: The Qlow equation to be calculated
    :param q2_eqtn: The Q2 equation to be calculated
    :return:
    """
    # get project folder path from input network
    proj_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(in_network))))

    # open xml
    xml_file_path = os.path.join(proj_path, "project.rs.xml")
    if not os.path.exists(xml_file_path):
        raise Exception("XML file for project does not exist. Return to Step 1: BRAT table to create XML.")
    xml_file = XMLBuilder(xml_file_path)

    # find input network XML element
    in_network_rel_path = find_relative_path(in_network, proj_path)                                    
    path_element = xml_file.find_by_text(in_network_rel_path)

    # find intermediates element for input network
    intermediates_element = xml_file.find_element_parent(xml_file.find_element_parent(path_element))
    if intermediates_element is None:
        raise Exception("Equations could not be added because parent element 'Intermediates' not found in XML.")

    # add regional curves element within intermediates
    ihyd_element = xml_file.add_sub_element(intermediates_element,
                                            name="Regional Curves",
                                            text="Equations for estimating streamflow")

    # add region element to XML if specified
    if region is not 0:
        xml_file.add_sub_element(ihyd_element, "Hydrological region", str(region))

    # add base flow equation to XML if specified or using generic
    if q_low_eqtn is None and region is 0:
        xml_file.add_sub_element(ihyd_element, name="Baseflow equation", text="(DAsqm ** 0.2098) + 1")
    elif q2_eqtn is None and region is not 0:
        xml_file.add_sub_element(ihyd_element, name="Baseflow equation", text="Not specified - see iHyd code.")
    else:
        xml_file.add_sub_element(ihyd_element, name="Baseflow equation", text=str(q_low_eqtn))

    # add high flow equation to XML if specified or using generic
    if q2_eqtn is None and region is 0:
        xml_file.add_sub_element(ihyd_element, name="Highflow equation", text="14.7 * (DAsqm ** 0.815)")
    elif q2_eqtn is None and region is not 0:
        xml_file.add_sub_element(ihyd_element, name="Highflow equation", text="Not specified - see iHyd code.")
    else:
        xml_file.add_sub_element(ihyd_element, name="Highflow equation", text=str(q2_eqtn))
    
    xml_file.write()

    
if __name__ == '__main__':
    main(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3],
        sys.argv[4])
