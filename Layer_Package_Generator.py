# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
# Name: Layer Package Generator
# Purpose: Finds existing layers in a project, generates them if they are missing and their base exists, and then puts
# them into a layer package
#
# Author: Braden Anderson
# Created on: 14 June 2018
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #


import arcpy
import os
import glob
from SupportingFunctions import find_folder, find_available_num_prefix, make_folder, make_layer
import re


def main(output_folder, layer_package_name, clipping_network):
    """
    Generates a layer package from a BRAT project
    :param output_folder: What output folder we want to use for our layer package
    :param layer_package_name: What we want to name our layer package
    :param clipping_network: What we want to clip our network to
    :return:
    """

    arcpy.env.overwriteOutput = 'TRUE'

    if layer_package_name == "None":
	layer_package_name = None
    if clipping_network == "None":
	clipping_network = None
        
    if layer_package_name is None:
        if clipping_network is not None:
            layer_package_name = "LayerPackage_Clipped"
        else:
            layer_package_name = "LayerPackage"

    validate_inputs(output_folder)

    project_folder = os.path.dirname(os.path.dirname(output_folder))
    inputs_folder = find_folder(project_folder, "Inputs")
    intermediates_folder = os.path.join(output_folder, "01_Intermediates")
    analyses_folder = os.path.join(output_folder, "02_Analyses")

    trib_code_folder = os.path.dirname(os.path.abspath(__file__))
    symbology_folder = os.path.join(trib_code_folder, 'BRATSymbology')

    try:
        check_for_layers(intermediates_folder, analyses_folder, inputs_folder, symbology_folder)
    except Exception as err:
        arcpy.AddMessage(
            "Something went wrong while checking for layers. The process will package the layers that exist.")
        arcpy.AddMessage("The error message thrown was the following:")
        arcpy.AddWarning(err)

    if clipping_network is not None:
        brat_table_clip, network_clip, cons_rest_clip, valid_clip = \
            create_clipped_layers(output_folder, clipping_network, symbology_folder)
    
    make_layer_package(output_folder, intermediates_folder, analyses_folder,
                       inputs_folder, symbology_folder, layer_package_name, clipping_network)


def create_clipped_layers(output_folder, clipping_network, symbology_folder):
    """
    Makes clipped layers of all BRAT outputs
    param output_folder: folder where BRAT outputs will be found
    param clipping_network: network which BRAT outputs will be clipped to (e.g. the perennial)
    param symbology_folder: folder where standardized BRAT layers are found
    """
    arcpy.AddMessage("Making clipped layers.....")
    proj_path = os.path.dirname(os.path.dirname(output_folder))
    intermediates_folder = find_folder(output_folder, 'Intermediates')
    analyses_folder = find_folder(output_folder, 'Analyses')
    buffer_folder = find_folder(intermediates_folder, "Buffers")
    
    # find relevant files
    network = find_file(proj_path, 'Inputs/*[0-9]*_Network/Network_*[0-9]*/*.shp')
    brat_table_file = find_brat_table_output(intermediates_folder)
    conservation_restoration_file = find_shape_file_with_field(analyses_folder, "oPBRC_CR")
    validation_file = find_shape_file_with_field(analyses_folder, "ExCategor")

    # clip all files
    network_clip = clip_file(network, clipping_network)
    brat_table_clip = clip_file(brat_table_file, clipping_network)
    cons_rest_clip = clip_file(conservation_restoration_file, clipping_network)
    if validation_file is not None:
        valid_clip = clip_file(validation_file, clipping_network)
    else:
        valid_clip = None

    # make new network layer
    make_clipped_layers(os.path.dirname(network), network_clip, clipping_network, symbology_folder)

    # make new buffers
    buf_30_symbol = os.path.join(symbology_folder, "buffer_30m.lyr")
    buf_100_symbol = os.path.join(symbology_folder, "buffer_100m.lyr")
    buf_30m = os.path.join(buffer_folder, "buffer_30m_clipped.shp")
    buf_100m = os.path.join(buffer_folder, "buffer_100m_clipped.shp")
    arcpy.Buffer_analysis(network_clip, buf_100m, "100 Meters", "", "ROUND")
    arcpy.Buffer_analysis(network_clip, buf_30m, "30 Meters", "", "ROUND")
    make_layer(buffer_folder, buf_30m, "30 m Buffer", buf_30_symbol, file_name="30mBuffer_clipped.lyr")
    make_layer(buffer_folder, buf_100m, "100 m Buffer", buf_100_symbol, file_name="100mBuffer_clipped.lyr")
               
    # make new intermediates layers
    inter_folders = filter(lambda x: os.path.isdir(os.path.join(intermediates_folder, x)),
                           os.listdir(intermediates_folder))
    perennial_folder = find_folder(intermediates_folder, "Perennial")
    if os.path.basename(buffer_folder) in inter_folders:
        inter_folders.remove(os.path.basename(buffer_folder))
    if os.path.basename(perennial_folder) in inter_folders:
        inter_folders.remove(os.path.basename(perennial_folder))
    if len(inter_folders) > 0:
        for folder_name in inter_folders:
            folder = os.path.join(intermediates_folder, folder_name)
            make_clipped_layers(folder, brat_table_clip, clipping_network, symbology_folder)

    # make new analyses layers
    capacity_folder = find_folder(analyses_folder, "Capacity")
    historic_folder = find_folder(capacity_folder, "HistoricCapacity")
    existing_folder = find_folder(capacity_folder, "ExistingCapacity")
    management_folder = find_folder(analyses_folder, "Management")
    validation_folder = find_folder(analyses_folder, "Validation")
    analyses_folders = [capacity_folder, historic_folder, existing_folder, management_folder]
    if len(analyses_folders) > 0:
        for folder in analyses_folders:
            make_clipped_layers(folder, cons_rest_clip, clipping_network, symbology_folder)
    if validation_file is not None:
        make_clipped_layers(validation_folder, valid_clip, clipping_network, symbology_folder)

    return brat_table_clip, network_clip, cons_rest_clip, valid_clip
        

def clip_file(shapefile, clipping_network):
    """
    Clips BRAT outputs to clipping network with standardized name
    param shapefile: BRAT output to be clipped
    param clipping_network: polyline to clip BRAT outputs to
    """
    if os.path.exists(shapefile):
        perennial_shapefile = shapefile.split('.')[0] + "_Perennial.shp"
        if os.path.exists(perennial_shapefile):
            arcpy.AddMessage('.........Using previously clipped ' + os.path.basename(perennial_shapefile))
            return perennial_shapefile
        elif shapefile.endswith('_Perennial.shp') or shapefile.endswith('_clipped.shp'):
            arcpy.AddMessage('.........Using previously clipped ' + os.path.basename(shapefile))
            return shapefile
        else:
            try:
                out_name = shapefile.split('.')[0] + "_clipped.shp"
                arcpy.Clip_analysis(shapefile, clipping_network, out_name)
                return out_name
            except Exception as err:
                print err
    else:
        arcpy.AddMessage("WARNING: Could not find " + shapefile + " to make clipped layers")


def make_clipped_layers(folder, shapefile, clipping_network, symbology_folder):
    """
    Makes clipped layers for all layer in folder based on shapefile that has been clipped
    param folder: folder where old layers will be found and new clipped layers stored
    param shapefile: shapefile layers will be based off
    param symbology_folder: folder where base layers will be found
    """
    lyrs = find_layers_in_folder(folder, None)
    for lyr in lyrs[:]:
        if lyr.endswith('_clipped.lyr'):
            lyrs.remove(lyr)
        if os.path.basename(lyr) == 'SurveyedBeaverDamLocations.lyr':
            lyrs.remove(lyr)
    for lyr in lyrs:
        name = os.path.basename(lyr)
        symbology = os.path.join(symbology_folder, name)
        desc = arcpy.Describe(lyr)
        out_name = str(desc.nameString)
        out_file = name.split('.')[0]+'_clipped.lyr'
        if os.path.exists(os.path.join(folder, out_file)):
            arcpy.Delete_management(os.path.join(folder, out_file))
        if os.path.exists(symbology):
            try:
                make_layer(folder, shapefile, new_layer_name=out_name,
                           symbology_layer=symbology, is_raster=False, file_name=out_file)
            except Exception as err:
                arcpy.AddMessage("WARNING: Failed to make " + out_file + ". Error thrown was:")
                arcpy.AddMessage(err)
        

def validate_inputs(output_folder):
    """
    Checks that the inputs are in the form that we want them to be
    :param output_folder: What output folder we want to base our layer package off of
    :return:
    """
    if not re.match(r'Output_\d\d', os.path.basename(output_folder)):
        raise Exception("Given output folder is invalid.\n\n" +
                        'Look for a folder formatted like "Output_##", where # represents any number')


def check_for_layers(intermediates_folder, analyses_folder, inputs_folder, symbology_folder):
    """
    Checks for what layers exist, and creates them if they do not exist
    :param intermediates_folder: Where our intermediates are kept
    :param analyses_folder: Where our analyses are kept
    :param inputs_folder: Where our inputs are kept
    :param symbology_folder: Where we pull symbology from
    :return:
    """
    arcpy.AddMessage("Recreating missing layers (if possible)...")
    check_intermediates(intermediates_folder, symbology_folder)
    check_analyses(analyses_folder, symbology_folder)
    check_inputs(inputs_folder, symbology_folder)


def check_intermediates(intermediates_folder, symbology_folder):
    """
    Checks for all the intermediate layers
    :param intermediates_folder: Where our intermediates are kept
    :param symbology_folder: Where we pull symbology from
    :return:
    """
    brat_table_file = find_brat_table_output(intermediates_folder)
    if brat_table_file == "":
        arcpy.AddMessage("Could not find BRAT Table output in intermediates, so could not generate layers for them")
        return

    check_buffer_layers(intermediates_folder, symbology_folder)

    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "UpstreamDrainageArea.lyr", brat_table_file, "TopographicMetrics",
                             "Upstream Drainage Area", "iGeo_DA")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "ReachSlope.lyr", brat_table_file, "TopographicMetrics",
                             "Reach Slope", "iGeo_Slope")

    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "LandUseIntensity.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Land Use Intensity", "iPC_LU")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "DistancetoClosestInfrastructure.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Distance to Canals & Ditches", "iPC_Canal")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "DistancetoClosestInfrastructure.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Distance to Closest Infrastructure", "oPC_Dist")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "DistancetoClosestInfrastructure.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Distance to Railroad", "iPC_Rail")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "DistancetoClosestInfrastructure.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Distance to Railroad in Valley Bottom", "iPC_RailVB")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "DistancetoClosestInfrastructure.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Distance to Road Crossing", "iPC_RoadX")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "DistancetoClosestInfrastructure.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Distance to Road", "iPC_Road")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "DistancetoClosestInfrastructure.lyr", brat_table_file, "AnthropogenicMetrics",
                             "Distance to Road in Valley Bottom", "iPC_RoadVB")

    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "AnabranchTypes.lyr", brat_table_file, "AnabranchHandler",
                             "Anabranch Types", "IsMainCh")

    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "HighflowStreamPower.lyr", brat_table_file, "Hydrology",
                             "Highflow Stream Power", "iHyd_SP2")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "BaseflowStreamPower.lyr", brat_table_file, "Hydrology",
                             "Baseflow Stream Power", "iHyd_SPLow")

    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "ExistingVegDamBuildingCapacity.lyr", brat_table_file, "VegDamCapacity",
                             "Existing Veg Dam Building Capacity", "oVC_EX")
    check_intermediate_layer(intermediates_folder, symbology_folder,
                             "HistoricVegDamBuildingCapacity.lyr", brat_table_file, "VegDamCapacity",
                             "Historic Veg Dam Building Capacity", "oVC_HPE")


def check_intermediate_layer(intermediates_folder, symbology_folder, symbology_layer_name, brat_table_file, folder_name,
                             layer_name, field_for_layer, layer_file_name=None):
    """
    Checks that the layer exists. If it has the proper field, and it missing, the layer will be created again
    :param intermediates_folder: The path to the intermediates folder
    :param symbology_folder: The path to the symbology folder
    :param symbology_layer_name: The name of the symbology layer, that we'll pull our symbology from
    :param brat_table_file: The BRAT table output, which we'll use for our layers
    :param folder_name: The name of the folder that we'll look in for the layer
    :param layer_name: The name we need to give to the layer (in the Table of Contents)
    :param field_for_layer: The name of the field we'll need for the layer
    :param layer_file_name: The name we'll give to the layer file (defaults to the name in the ToC, without spaces)
    :return:
    """
    fields = [f.name for f in arcpy.ListFields(brat_table_file)]
    if field_for_layer not in fields:  # we don't want to create the layer if the field isn't in the BRAT table file
        return

    if layer_file_name is None:
        layer_file_name = layer_name.replace(" ", "")
    layer_symbology = os.path.join(symbology_folder, symbology_layer_name)

    layer_folder = find_folder(intermediates_folder, folder_name)

    if layer_folder is None:
        layer_folder = make_folder(intermediates_folder,
                                   find_available_num_prefix(intermediates_folder) + "_" + folder_name)

    layer_path = os.path.join(layer_folder, layer_file_name)
    if not layer_path.endswith(".lyr"):
        layer_path += '.lyr'

    if not os.path.exists(layer_path):
        make_layer(layer_folder, brat_table_file, layer_name, layer_symbology, file_name=layer_file_name)


def check_layer(layer_path, base_path, symbology_layer=None, is_raster=False, layer_name=None):
    """
    If the base exists, but the layer does not, makes the layer
    :param layer_path: The layer we want to check for
    :param base_path: The file that the layer is based off of
    :param symbology_layer: The symbology to apply to the new layer (if necessary)
    :param is_raster: If the new layer is a raster
    :param layer_name: The name of the layer to check
    :return:
    """
    if not os.path.exists(layer_path) and os.path.exists(base_path):
        output_folder = os.path.dirname(layer_path)
        if layer_name is None:
            layer_name = os.path.basename(layer_path)
        make_layer(output_folder, base_path, layer_name, symbology_layer, is_raster=is_raster)


def find_brat_table_output(intermediates_folder):
    """
    Finds the path to the BRAT Table output for use in generating layers
    :param intermediates_folder: Where the BRAT Table output should be
    :return:
    """
    brat_table_file = ""
    for shape_dir in os.listdir(intermediates_folder):
        if shape_dir.endswith(".shp"):
            brat_table_file = os.path.join(intermediates_folder, shape_dir)

    return brat_table_file


def check_buffer_layers(intermediates_folder, symbology_folder):
    """
    Finds the buffer folder, and checks that it has the
    :param intermediates_folder: The path to the intermediates folder
    :param symbology_folder: The path to the symbology folder
    :return:
    """
    buffer_folder = find_folder(intermediates_folder, "Buffers")

    buffer_100m = os.path.join(buffer_folder, "buffer_100m.shp")
    buffer_100m_layer = os.path.join(buffer_folder, "100mBuffer.lyr")
    buffer_100m_symbology = os.path.join(symbology_folder, "buffer_100m.lyr")
    check_layer(buffer_100m_layer, buffer_100m, buffer_100m_symbology, is_raster=False, layer_name='100 m Buffer')

    buffer_30m = os.path.join(buffer_folder, "buffer_30m.shp")
    buffer_30m_layer = os.path.join(buffer_folder, "30mBuffer.lyr")
    buffer_30m_symbology = os.path.join(symbology_folder, "buffer_30m.lyr")
    check_layer(buffer_30m_layer, buffer_30m, buffer_30m_symbology, is_raster=False, layer_name='30 m Buffer')


def check_analyses(analyses_folder, symbology_folder):
    """
    Checks for all the intermediate layers
    :param analyses_folder: Where our analyses are kept
    :param symbology_folder: Where we pull symbology from
    :return:
    """
    capacity_folder = find_folder(analyses_folder, "Capacity")
    historic_capacity_folder = find_folder(capacity_folder, "HistoricCapacity")
    existing_capacity_folder = find_folder(capacity_folder, "ExistingCapacity")
    management_folder = find_folder(analyses_folder, "Management")

    check_analyses_layer(analyses_folder, existing_capacity_folder, "Existing Dam Building Capacity",
                         symbology_folder, "ExistingDamBuildingCapacity.lyr", "oCC_EX")
    check_analyses_layer(analyses_folder, historic_capacity_folder, "Historic Dam Building Capacity",
                         symbology_folder, "HistoricDamBuildingCapacity.lyr", "oCC_HPE")
    check_analyses_layer(analyses_folder, existing_capacity_folder, "Existing Dam Complex Size",
                         symbology_folder, "ExistingDamComplexSize.lyr", "mCC_EX_Ct")
    check_analyses_layer(analyses_folder, historic_capacity_folder, "Historic Dam Complex Size",
                         symbology_folder, "HistoricDamComplexSize.lyr", "mCC_HPE_Ct")

    check_analyses_layer(analyses_folder, management_folder, "Unsuitable or Limited Dam Building Opportunities",
                         symbology_folder, "UnsuitableorLimitedDamBuildingOpportunities.lyr", "oPBRC_UD")
    check_analyses_layer(analyses_folder, management_folder, "Risk of Undesirable Dams",
                         symbology_folder, "RiskofUndesirableDams.lyr", "oPBRC_UI")
    check_analyses_layer(analyses_folder, management_folder, "Beaver Dam Constraints and Opportunities",
                         symbology_folder, "BeaverDamConstraintsandOpportunities.lyr", "oPBRC_CR")


def check_analyses_layer(analyses_folder, layer_base_folder, layer_name, symbology_folder,
                         symbology_file_name, field_name, layer_file_name=None):
    """
    Checks if an analyses layer exists. If it does not, it looks for a shape file that can create the proper symbology.
    If it finds a proper shape file, it creates the layer that was missing
    :param analyses_folder: The root of the analyses folder
    :param layer_base_folder: The folder containing the layer file
    :param layer_name: The name of the layer to create
    :param symbology_folder: The path to the symbology folder
    :param symbology_file_name: The name of the symbology layer we want to pull from
    :param field_name: The name of the field we'll be basing our symbology off of
    :param layer_file_name: The name of the layer file (if different from the layer_name without spaces)
    :return:
    """
    if layer_file_name is None:
        layer_file_name = layer_name.replace(" ", "") + ".lyr"

    layer_file = os.path.join(layer_base_folder, layer_file_name)
    if os.path.exists(layer_file):  # if the layer already exists, we don't care, we can exit the function
        return

    shape_file = find_shape_file_with_field(analyses_folder, field_name)
    if shape_file is None:
        return

    layer_symbology = os.path.join(symbology_folder, symbology_file_name)

    make_layer(layer_base_folder, shape_file, layer_name, symbology_layer=layer_symbology)


def find_shape_file_with_field(folder, field_name):
    """
    Looks for a file in the given folder that has the field name we're looking for
    :param folder: The folder to look in
    :param field_name: The field name we're looking for
    :return: The file path that has the field we want
    """
    for check_file in os.listdir(folder):
        if check_file.endswith(".shp"):
            file_path = os.path.join(folder, check_file)
            file_fields = [f.name for f in arcpy.ListFields(file_path)]
            if field_name in file_fields:
                return file_path
    return None


def check_inputs(inputs_folder, symbology_folder):
    """
    Checks for all the intermediate layers
    :param inputs_folder: Where our inputs are kept
    :param symbology_folder: Where we pull symbology from
    :return:
    """
    vegetation_folder = find_folder(inputs_folder, "Vegetation")
    network_folder = find_folder(inputs_folder, "Network")
    topo_folder = find_folder(inputs_folder, "Topography")
    anthropogenic_folder = find_folder(inputs_folder, "Anthropogenic")

    ex_veg_folder = find_folder(vegetation_folder, "ExistingVegetation")
    hist_veg_folder = find_folder(vegetation_folder, "HistoricVegetation")

    valley_bottom_folder = find_folder(anthropogenic_folder, "ValleyBottom")
    road_folder = find_folder(anthropogenic_folder, "Roads")
    railroad_folder = find_folder(anthropogenic_folder, "Railroads")
    canals_folder = find_folder(anthropogenic_folder, "Canals")
    land_use_folder = find_folder(anthropogenic_folder, "LandUse")
    land_ownership_folder = find_folder(anthropogenic_folder, "LandOwnership")

    ex_veg_suitability_symbology = os.path.join(symbology_folder, "Existing_Veg_Suitability.lyr")
    ex_veg_riparian_symbology = os.path.join(symbology_folder, "Existing_Veg_Riparian.lyr")
    ex_veg_evt_type_symbology = os.path.join(symbology_folder, "Existing_Veg_EVT_Type.lyr")
    ex_veg_evt_class_symbology = os.path.join(symbology_folder, "Existing_Veg_EVT_Class.lyr")
    ex_veg_class_name_symbology = os.path.join(symbology_folder, "Existing_Veg_EVT_Name.lyr")

    hist_veg_group_symbology = os.path.join(symbology_folder, "Historic_Veg_BPS_Type.lyr")
    hist_veg_bps_name_symbology = os.path.join(symbology_folder, "Historic_Veg_BPS_Name.lyr")
    hist_veg_suitability_symbology = os.path.join(symbology_folder, "Historic_Veg_Suitability.lyr")
    hist_veg_riparian_symbology = os.path.join(symbology_folder, "Historic_Veg_Riparian.lyr")

    network_symbology = os.path.join(symbology_folder, "Network.lyr")
    landuse_symbology = os.path.join(symbology_folder, "Land_Use_Raster.lyr")
    land_ownership_symbology = os.path.join(symbology_folder, "SurfaceManagementAgency.lyr")
    canals_symbology = os.path.join(symbology_folder, "CanalsDitches.lyr")
    roads_symbology = os.path.join(symbology_folder, "Roads.lyr")
    railroads_symbology = os.path.join(symbology_folder, "Railroads.lyr")
    valley_bottom_symbology = os.path.join(symbology_folder, "ValleyBottom_Fill.lyr")
    valley_bottom_outline_symbology = os.path.join(symbology_folder, "ValleyBottom_Outline.lyr")
    flow_direction_symbology = os.path.join(symbology_folder, "FlowDirection.lyr")

    ex_veg_destinations = find_destinations(ex_veg_folder)
    make_input_layers(ex_veg_destinations, "Existing Vegetation Suitability for Beaver Dam Building",
                      symbology_layer=ex_veg_suitability_symbology, is_raster=True, file_name="ExVegSuitability")
    make_input_layers(ex_veg_destinations, "Existing Riparian",
                      symbology_layer=ex_veg_riparian_symbology, is_raster=True)
    make_input_layers(ex_veg_destinations, "Veg Type - EVT Type",
                      symbology_layer=ex_veg_evt_type_symbology, is_raster=True)
    make_input_layers(ex_veg_destinations, "Veg Type - EVT Class",
                      symbology_layer=ex_veg_evt_class_symbology, is_raster=True)
    make_input_layers(ex_veg_destinations, "Veg Type - EVT Name",
                      symbology_layer=ex_veg_class_name_symbology, is_raster=True)

    hist_veg_destinations = find_destinations(hist_veg_folder)
    make_input_layers(hist_veg_destinations, "Historic Vegetation Suitability for Beaver Dam Building",
                      symbology_layer=hist_veg_suitability_symbology, is_raster=True, file_name="HistVegSuitability")
    make_input_layers(hist_veg_destinations, "Veg Type - BPS Type",
                      symbology_layer=hist_veg_group_symbology, is_raster=True, check_field="GROUPVEG")
    make_input_layers(hist_veg_destinations, "Veg Type - BPS Name",
                      symbology_layer=hist_veg_bps_name_symbology, is_raster=True)
    make_input_layers(hist_veg_destinations, "Historic Riparian",
                      symbology_layer=hist_veg_riparian_symbology, is_raster=True, check_field="GROUPVEG")

    network_destinations = find_destinations(network_folder)
    make_input_layers(network_destinations, "Network", symbology_layer=network_symbology, is_raster=False)
    make_input_layers(network_destinations, "Flow Direction", symbology_layer=flow_direction_symbology, is_raster=False)

    make_topo_layers(topo_folder)

    # add landuse raster to the project
    if land_use_folder is not None:
        landuse_destinations = find_destinations(land_use_folder)
        make_input_layers(landuse_destinations, "Land Use Raster", symbology_layer=landuse_symbology, is_raster=True)

    # add the anthropogenic inputs to the project
    if valley_bottom_folder is not None:
        vally_bottom_destinations = find_destinations(valley_bottom_folder)
        make_input_layers(vally_bottom_destinations, "Valley Bottom Fill",
                          symbology_layer=valley_bottom_symbology, is_raster=False)
        make_input_layers(vally_bottom_destinations, "Valley Bottom Outline",
                          symbology_layer=valley_bottom_outline_symbology, is_raster=False)

    # add road layers to the project
    if road_folder is not None:
        road_destinations = find_destinations(road_folder)
        make_input_layers(road_destinations, "Roads", symbology_layer=roads_symbology, is_raster=False)

    # add railroad layers to the project
    if railroad_folder is not None:
        rr_destinations = find_destinations(railroad_folder)
        make_input_layers(rr_destinations, "Railroads", symbology_layer=railroads_symbology, is_raster=False)

    if canals_folder is not None:
        canal_destinations = find_destinations(canals_folder)
        make_input_layers(canal_destinations, "Canals & Ditches", symbology_layer=canals_symbology, is_raster=False)

    # add land ownership layers to the project
    if land_ownership_folder is not None:
        ownership_destinations = find_destinations(land_ownership_folder)
        make_input_layers(ownership_destinations, "Land Ownership",
                          symbology_layer=land_ownership_symbology, is_raster=False)


def make_topo_layers(topo_folder):
    """
    Writes the layers
    :param topo_folder: We want to make layers for the stuff in this folder
    :return:
    """
    source_code_folder = os.path.dirname(os.path.abspath(__file__))
    symbology_folder = os.path.join(source_code_folder, 'BRATSymbology')
    dem_symbology = os.path.join(symbology_folder, "DEM.lyr")
    slope_symbology = os.path.join(symbology_folder, "Slope.lyr")

    for folder in os.listdir(topo_folder):
        dem_folder_path = os.path.join(topo_folder, folder)
        for file_name in os.listdir(dem_folder_path):
            if file_name.endswith(".tif"):
                dem_file = os.path.join(dem_folder_path, file_name)
                if not os.path.exists(os.path.join(dem_folder_path, "DEM.lyr")) and os.path.exists(dem_file):
                    make_layer(dem_folder_path, dem_file, "DEM", dem_symbology, is_raster=True)

        hillshade_folder = find_folder(dem_folder_path, "Hillshade")
        hillshade_file = os.path.join(hillshade_folder, "Hillshade.tif")
        if not os.path.exists(os.path.join(hillshade_folder, "Hillshade.lyr")) and os.path.exists(hillshade_file):
            make_layer(hillshade_folder, hillshade_file, "Hillshade", is_raster=True)

        slope_folder = find_folder(dem_folder_path, "Slope")
        slope_file = os.path.join(slope_folder, "Slope.tif")
        if not os.path.exists(os.path.join(slope_folder, "Slope.lyr")) and os.path.exists(slope_file):
            make_layer(slope_folder, slope_file, "Slope", slope_symbology, is_raster=True)


def find_destinations(root_folder):
    """
    Finds all the .shp and .tif files in a directory, and returns an array with the paths to them
    :param root_folder: The root folder where we want to find shape files
    :return:
    """
    destinations = []
    for root, dirs, files in os.walk(root_folder):
        for check_file in files:
            if check_file.endswith(".shp") or check_file.endswith('.tif'):
                destinations.append(os.path.join(root, check_file))
    return destinations


def make_input_layers(destinations, layer_name, is_raster, symbology_layer=None, file_name=None, check_field=None):
    """
    Makes the layers for everything in the folder
    :param destinations: A list of paths to our inputs
    :param layer_name: The name of the layer
    :param is_raster: Whether or not it's a raster
    :param symbology_layer: The base for the symbology
    :param file_name: The name for the file (if it's different from the layerName)
    :param check_field: The name of the field that the symbology is based on
    :return:
    """
    if file_name is None:
        file_name = layer_name
    for destination in destinations:
        skip_loop = False
        dest_dir_name = os.path.dirname(destination)

        if file_name is None:
            file_name = layer_name.replace(" ", "")
        new_layer_save = os.path.join(dest_dir_name, file_name.replace(' ', ''))
        if not new_layer_save.endswith(".lyr"):
            new_layer_save += ".lyr"
        if os.path.exists(new_layer_save):
            skip_loop = True
        if check_field:
            fields = [f.name for f in arcpy.ListFields(destination)]
            if check_field not in fields:
                # Skip the loop if the base doesn't support
                skip_loop = True

        if not skip_loop:
            make_layer(dest_dir_name, destination, layer_name,
                       symbology_layer=symbology_layer, is_raster=is_raster, file_name=file_name)


def make_layer_package(output_folder, intermediates_folder, analyses_folder,
                       inputs_folder, symbology_folder, layer_package_name, clipping_network):
    """
    Makes a layer package for the project
    :param output_folder: Folder to output the layer package to
    :param intermediates_folder: Folder containing intermediates layers
    :param analyses_folder: Folder containing analyses layers
    :param inputs_folder: Folder containing inputs layers
    :param symbology_folder: Folder containing symbology layers
    :param layer_package_name: Name for the layer package output
    :param clipping_network: Network to clip the layer package with
    :return:
    """
    if layer_package_name == "" or layer_package_name is None:
        layer_package_name = "LayerPackage"
    if not layer_package_name.endswith(".lpk"):
        layer_package_name += ".lpk"

    arcpy.AddMessage("Assembling Layer Package...")
    empty_group_layer = os.path.join(symbology_folder, "EmptyGroupLayer.lyr")

    mxd = arcpy.mapping.MapDocument("CURRENT")
    mxd.relativePaths = False
    df = arcpy.mapping.ListDataFrames(mxd)[0]
    for lyr in arcpy.mapping.ListLayers(mxd, "", df):
        arcpy.mapping.RemoveLayer(df, lyr)

    analyses_layer = get_analyses_layer(analyses_folder, empty_group_layer, df, mxd, clipping_network)
    inputs_layer = get_inputs_layer(empty_group_layer, inputs_folder, df, mxd, clipping_network)
    intermediates_layer = get_intermediates_layers(empty_group_layer, intermediates_folder, df, mxd, clipping_network)
    output_layer = group_layers(empty_group_layer, "Output", [intermediates_layer, analyses_layer], df, mxd)
    output_layer = group_layers(empty_group_layer, layer_package_name[:-4],
                                [output_layer, inputs_layer], df, mxd, remove_layer=False)

    layer_package = os.path.join(output_folder, layer_package_name)
    arcpy.AddMessage("Saving Layer Package...")
    arcpy.PackageLayer_management(output_layer, layer_package)


def get_analyses_layer(analyses_folder, empty_group_layer, df, mxd, clipping_network):
    """
    Returns the layers we want for the 'BRAT Outputs' section
    :param analyses_folder: folder holding capacity, conservation restoration, and validation outputs
    :param empty_group_layer: empty group layer
    :param df: data frame where layer package is being built
    :param mxd: ArcMap document where layer package is being built
    :param clipping_network: The network BRAT outputs will be clipped
    :return:
    """
    capacity_folder = find_folder(analyses_folder, "Capacity")
    existing_capacity_folder = find_folder(capacity_folder, "ExistingCapacity")
    if clipping_network is None:
        existing_density_lyr = find_file(existing_capacity_folder, 'ExistingDamBuildingCapacity.lyr')
        existing_complex_lyr = find_file(existing_capacity_folder, 'ExistingDamComplexSize.lyr')
    else:
        existing_density_lyr = find_file(existing_capacity_folder, 'ExistingDamBuildingCapacity_clipped.lyr')
        existing_complex_lyr = find_file(existing_capacity_folder, 'ExistingDamComplexSize_clipped.lyr')
    historic_capacity_folder = find_folder(capacity_folder, "HistoricCapacity")
    if clipping_network is None:
        historic_density_lyr = find_file(historic_capacity_folder, 'HistoricDamBuildingCapacity.lyr')
        historic_complex_lyr = find_file(historic_capacity_folder, 'HistoricDamComplexSize.lyr')
    else:
        historic_density_lyr = find_file(historic_capacity_folder, 'HistoricDamBuildingCapacity_clipped.lyr')
        historic_complex_lyr = find_file(historic_capacity_folder, 'HistoricDamComplexSize_clipped.lyr')
    management_folder = find_folder(analyses_folder, "Management")
    validation_folder = find_folder(analyses_folder, "Validation")

    existing_density_group = group_layers(empty_group_layer, "Dam Density", [existing_density_lyr], df, mxd)
    existing_complex_group = group_layers(empty_group_layer, "Size of Complex", [existing_complex_lyr], df, mxd)
    existing_capacity_layers = [existing_complex_group, existing_density_group]
    existing_capacity_layer = group_layers(empty_group_layer, "Existing Capacity", existing_capacity_layers, df, mxd)

    historic_density_group = group_layers(empty_group_layer, "Dam Density", [historic_density_lyr], df, mxd)
    historic_complex_group = group_layers(empty_group_layer, "Size of Complex", [historic_complex_lyr], df, mxd)
    historic_capacity_layers = [historic_complex_group, historic_density_group]
    historic_capacity_layer = group_layers(empty_group_layer, "Historic Capacity", historic_capacity_layers, df, mxd)

    management_layers = find_layers_in_folder(management_folder, clipping_network)
    management_layer = group_layers(empty_group_layer, "Management", management_layers, df, mxd)
    validation_layers = find_layers_in_folder(validation_folder, clipping_network)
    validation_layer = group_layers(empty_group_layer, "Validation", validation_layers, df, mxd)
    
    capacity_layer = group_layers(empty_group_layer, "Capacity",
                                  [historic_capacity_layer, existing_capacity_layer], df, mxd)
    output_layer = group_layers(empty_group_layer, "Beaver Restoration Assessment Tool - BRAT",
                                [management_layer, capacity_layer, validation_layer], df, mxd)

    return output_layer


def get_inputs_layer(empty_group_layer, inputs_folder, df, mxd, clipping_network):
    """
    Gets all the input layers, groups them properly, returns the layer
    :param empty_group_layer: The base to build the group layer with
    :param inputs_folder: Path to the inputs folder
    :param df: The dataframe we're working with
    :param mxd: The map document we're working with
    :param clipping_network: The network to clip th layer with
    :return: layer for inputs
    """
    vegetation_folder = find_folder(inputs_folder, "_Vegetation")
    ex_veg_folder = find_folder(vegetation_folder, "_ExistingVegetation")
    hist_veg_folder = find_folder(vegetation_folder, "_HistoricVegetation")

    network_folder = find_folder(inputs_folder, "_Network")

    topo_folder = find_folder(inputs_folder, "_Topography")

    anthropogenic_folder = find_folder(inputs_folder, "Anthropogenic")
    valley_folder = find_folder(anthropogenic_folder, "ValleyBottom")
    roads_folder = find_folder(anthropogenic_folder, "Roads")
    railroads_folder = find_folder(anthropogenic_folder, "Railroads")
    canals_folder = find_folder(anthropogenic_folder, "Canals")
    land_use_folder = find_folder(anthropogenic_folder, "LandUse")

    ex_veg_layers = find_instance_layers(ex_veg_folder, None)
    ex_veg_layer = group_layers(empty_group_layer, "Existing Vegetation", ex_veg_layers, df, mxd)
    hist_veg_layers = find_instance_layers(hist_veg_folder, None)
    hist_veg_layer = group_layers(empty_group_layer, "Historic Vegetation", hist_veg_layers, df, mxd)
    veg_layer = group_layers(empty_group_layer, "Vegetation", [hist_veg_layer, ex_veg_layer], df, mxd)

    network_layers = find_instance_layers(network_folder, clipping_network)
    network_layer = group_layers(empty_group_layer, "Network", network_layers, df, mxd)

    dem_layers = find_instance_layers(topo_folder, None)
    hillshade_layers = find_dem_derivative(topo_folder, "Hillshade")
    slope_layers = find_dem_derivative(topo_folder, "Slope")
    flow_layers = find_dem_derivative(topo_folder, "Flow")
    topo_layer = group_layers(empty_group_layer, "Topography",
                              hillshade_layers + dem_layers + slope_layers + flow_layers, df, mxd)

    valley_layers = find_instance_layers(valley_folder, None)
    valley_layer = group_layers(empty_group_layer, "Valley Bottom", valley_layers, df, mxd)
    road_layers = find_instance_layers(roads_folder, None)
    road_layer = group_layers(empty_group_layer, "Roads", road_layers, df, mxd)
    railroad_layers = find_instance_layers(railroads_folder, None)
    railroad_layer = group_layers(empty_group_layer, "Railroads", railroad_layers, df, mxd)
    canal_layers = find_instance_layers(canals_folder, None)
    canal_layer = group_layers(empty_group_layer, "Canals", canal_layers, df, mxd)
    land_use_layers = find_instance_layers(land_use_folder, None)
    land_use_layer = group_layers(empty_group_layer, "Land Use", land_use_layers, df, mxd)
    anthropogenic_layer = group_layers(empty_group_layer, "Anthropogenic Layers",
                                       [valley_layer, road_layer, railroad_layer, canal_layer, land_use_layer], df, mxd)

    return group_layers(empty_group_layer, "Inputs",
                        [topo_layer, veg_layer, network_layer, anthropogenic_layer], df, mxd)


def get_intermediates_layers(empty_group_layer, intermediates_folder, df, mxd, clipping_network):
    """
    Returns a group layer with all of the intermediates
    :param empty_group_layer: The base to build the group layer with
    :param intermediates_folder: Path to the intermediates folder
    :param df: The dataframe we're working with
    :param mxd: The map document we're working with
    :param clipping_network: The network to clip the layer with
    :return: Layer for intermediates
    """
    intermediate_layers = []
    
    # findAndGroupLayers(intermediate_layers, intermediatesFolder,
    # "AnthropogenicIntermediates", "Anthropogenic Intermediates", emptyGroupLayer, df, mxd)
    anthropogenic_metrics_folder = find_folder(intermediates_folder, "AnthropogenicMetrics")
    if anthropogenic_metrics_folder:
        sorted_anthropogenic_layers = []
        wanted_anthropogenic_layers = []
        existing_anthropogenic_layers = find_layers_in_folder(anthropogenic_metrics_folder, clipping_network)

    if clipping_network is not None:
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoCanal_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoPointsofDiversion_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRailroad_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRailroadinValleyBottom_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRoad_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRoadCrossing_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRoadinValleyBottom_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoClosestInfrastructure_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "LandOwnershipperReach_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "PriorityBeaverTranslocationAreas_clipped.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "LandUseIntensity_clipped.lyr"))
    else:

        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoCanal.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoPointsofDiversion.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRailroad.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRailroadinValleyBottom.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRoad.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRoadCrossing.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoRoadinValleyBottom.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "DistancetoClosestInfrastructure.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "LandOwnershipperReach.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "PriorityBeaverTranslocationAreas.lyr"))
        wanted_anthropogenic_layers.append(os.path.join(anthropogenic_metrics_folder,
                                                        "LandUseIntensity.lyr"))

    for layer in wanted_anthropogenic_layers:
        if layer in existing_anthropogenic_layers:
            sorted_anthropogenic_layers.append(layer)

    intermediate_layers.append(group_layers(empty_group_layer,
                                            "Anthropogenic Intermediates", sorted_anthropogenic_layers, df, mxd))

    find_and_group_layers(intermediate_layers, intermediates_folder,
                          "VegDamCapacity", "Overall Vegetation Dam Capacity",
                          empty_group_layer, df, mxd, clipping_network)
    find_and_group_layers(intermediate_layers, intermediates_folder,
                          "Buffers", "Buffers",
                          empty_group_layer, df, mxd, clipping_network)
    find_and_group_layers(intermediate_layers, intermediates_folder,
                          "Hydrology", "Hydrology",
                          empty_group_layer, df, mxd, clipping_network)
    find_and_group_layers(intermediate_layers, intermediates_folder,
                          "AnabranchHandler", "Anabranch Handler",
                          empty_group_layer, df, mxd, clipping_network)
    find_and_group_layers(intermediate_layers, intermediates_folder,
                          "TopographicMetrics", "Topographic Index",
                          empty_group_layer, df, mxd, clipping_network)
    find_and_group_layers(intermediate_layers, intermediates_folder,
                          "Perennial", "Perennial",
                          empty_group_layer, df, mxd, clipping_network)

    return group_layers(empty_group_layer, "Intermediates", intermediate_layers, df, mxd)


def find_and_group_layers(layers_list, folder_base, folder_name,
                          group_layer_name, empty_group_layer, df, mxd, clipping_network):
    """
    Looks for the folder that matches what we're looking for, then groups them together. Adds that grouped layer to the
    list of grouped layers that it was given
    :param layers_list: The list of layers that we will add our grouped layer to
    :param folder_base: Path to the folder that contains the folder we want
    :param folder_name: The name of the folder to look in
    :param group_layer_name: What we want to name the group layer
    :param empty_group_layer: The base to build the group layer with
    :param df: The dataframe we're working with
    :param mxd: The map document we're working with
    :param clipping_network: The network to clip the layer with
    :return:
    """
    folder_path = find_folder(folder_base, folder_name)
    if folder_path:
        layers = find_layers_in_folder(folder_path, clipping_network)

        layers_list.append(group_layers(empty_group_layer, group_layer_name, layers, df, mxd))


def find_instance_layers(root_folder, clipping_network):
    """
    Finds every layer when buried beneath an additional layer of folders (ie, in DEM_1, DEM_2, DEM_3, etc)
    :param root_folder: The path to the folder root
    :param clipping_network: The network to clip the layer with
    :return: A list of layers
    """
    if root_folder is None:
        return []

    layers = []
    for instance_folder in os.listdir(root_folder):
        instance_folder_path = os.path.join(root_folder, instance_folder)
        layers += find_layers_in_folder(instance_folder_path, clipping_network)
    return layers


def find_dem_derivative(root_folder, dir_name, clipping_network=None):
    """
    Designed to look specifically for flow, slope, and hillshade layers
    :param root_folder: Where we look
    :param dir_name: The directory we're looking for
    :return:
    """
    layers = []
    for instance_folder in os.listdir(root_folder):
        instance_folder_path = os.path.join(os.path.join(root_folder, instance_folder), dir_name)
        layers += find_layers_in_folder(instance_folder_path, clipping_network)
    return layers


def find_layers_in_folder(folder_root, clipping_network):
    """
    Returns a list of all layers in a folder
    :param folder_root: Where we want to look
    :param clipping_network: The network to clip the layer with
    :return:
    """
    layers = []
    if folder_root is None:
        return layers
    for instance_file in os.listdir(folder_root):
        if clipping_network is not None:
            if instance_file.endswith("_clipped.lyr"):
                layers.append(os.path.join(folder_root, instance_file))
            elif os.path.basename(instance_file) == "SurveyedBeaverDamLocations.lyr":
                layers.append(os.path.join(folder_root, instance_file))
        elif instance_file.endswith(".lyr"):
            layers.append(os.path.join(folder_root, instance_file))
    return layers


def group_layers(group_layer, group_name, layers, df, mxd, remove_layer=True):
    """
    Groups a bunch of layers together
    :param group_layer: The empty group layer we'll add stuff to
    :param group_name: The name of the group layer
    :param layers: The list of layers we want to put together
    :param df:
    :param mxd:
    :param remove_layer: Tells us if we should remove the layer from the map display
    :return: The layer that we put our layers in
    """
    if layers == [] or layers is None:
        return None

    layers = [x for x in layers if x is not None]  # remove none type from the layers

    group_layer = arcpy.mapping.Layer(group_layer)
    group_layer.name = group_name
    group_layer.description = "Made Up Description"
    arcpy.mapping.AddLayer(df, group_layer, "BOTTOM")
    group_layer = arcpy.mapping.ListLayers(mxd, group_name, df)[0]

    for layer in layers:
        if isinstance(layer, arcpy.mapping.Layer):
            layer_instance = layer
        else:
            layer_instance = arcpy.mapping.Layer(layer)

        arcpy.mapping.AddLayerToGroup(df, group_layer, layer_instance)
    
    if remove_layer:
        arcpy.mapping.RemoveLayer(df, group_layer)

    return group_layer


def find_file(proj_path, file_pattern):
    """
    Finds and returns a specific file
    :param proj_path: The path to the project folder
    :param file_pattern: A string representing the pattern to follow to get to the file
    :return: The filepath retrieved
    """

    search_path = os.path.join(proj_path, file_pattern)
    if len(glob.glob(search_path)) > 0:
        file_path = glob.glob(search_path)[0]
    else:
        file_path = None

    return file_path

if __name__ == "__main__":
    main(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3])
