# -------------------------------------------------------------------------------
# Name:        BRAT Table
# Purpose:     Builds the initial table to run through the BRAT tools
#
# Author:      Jordan Gilbert
#
# Created:     09/2016
# Copyright:   (c) Jordan 2016
# Licence:     <your licence>
# -------------------------------------------------------------------------------

import arcpy
from arcpy.sa import *
import os
import sys
import datetime
import time
import FindBraidedNetwork
import BRAT_Braid_Handler
from SupportingFunctions import make_layer, make_folder, getUUID, find_relative_path, write_xml_element_with_path
import XMLBuilder
import SupportingFunctions

reload(XMLBuilder)
XMLBuilder = XMLBuilder.XMLBuilder

reload(FindBraidedNetwork)
reload(BRAT_Braid_Handler)


def main(
    proj_path,
    seg_network,
    in_DEM,
    flow_acc,
    coded_veg,
    coded_hist,
    valley_bottom,
    road,
    railroad,
    canal,
    landuse,
    ownership,
    perennial_network,
    out_name,
    description,
    find_clusters,
    should_segment_network,
    segment_by_ownership,
    is_verbose):

    """
    Calculates, for each stream network segment, the attributes needed to trun the BRAT tools.
    :param proj_path: Path to the BRAT project folder.
    :param seg_network: The segmented (300m) network.
    :param in_DEM: The DEM for the entire project.
    :param flow_acc: The flow accumulation raster.
    :param coded_veg: The landfire EVT layer
    :param coded_hist: The landfire BPS layer
    :param valley_bottom: The valley bottom polygon that is associated with the input stream network.
    :param road: The shapefile containing all roads for the area
    :param railroad: The shapefile containing all railroads for the area
    :param canal: The shapefile containing all canals for the area
    :param landuse: The raster containing all land use data for the area
    :param ownership: The shapefile contating all land ownership data for the area
    :param perennial_network: The perennial network of streams
    :param out_name: The name for the output BRAT Table.
    :param description: A short description of the run that will be added to the XML
    :param find_clusters: If true, this option will create a ClusterID field and populate it
    :param should_segment_network: If true, this option divides reaches based on the roads input.
    :param segment_by_ownership: If true, this option divides reaches based on the land ownership input.
    :param is_verbose:  If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return:
    """

    if flow_acc == "None":
        flow_acc = None
    if perennial_network == "None":
        perennial_network = None

    find_clusters = parse_input_bool(find_clusters)
    should_segment_network = parse_input_bool(should_segment_network)
    segment_by_ownership = parse_input_bool(segment_by_ownership)
    is_verbose = parse_input_bool(is_verbose)

    scratch = 'in_memory'
    #arcpy.env.workspace = scratch
    arcpy.env.overwriteOutput = True
    arcpy.env.outputZFlag = "Disabled"
    arcpy.env.outputMFlag = "Disabled"
    arcpy.CheckOutExtension("Spatial")


    # --check input projections--
    validate_inputs(seg_network, road, railroad, canal, is_verbose)

    arcpy.env.outputCoordinateSystem = seg_network

    # name and create output folder
    new_output_folder, intermediate_folder, seg_network_copy = build_output_folder(proj_path, out_name, seg_network, road,
                                                                                   should_segment_network, ownership, segment_by_ownership,
                                                                                   is_verbose)

    # --check input network fields--
    # add flowline reach id field ('ReachID') if it doens't already exist
    # this field allows for more for more 'stable' joining
    fields = [f.name for f in arcpy.ListFields(seg_network_copy)]
    if 'ReachID' not in fields:
        arcpy.AddField_management(seg_network_copy, 'ReachID', 'LONG')
        with arcpy.da.UpdateCursor(seg_network_copy, ['FID', 'ReachID']) as cursor:
            for row in cursor:
                row[1] = row[0]
                cursor.updateRow(row)

    # --create network buffers for analyses--
    # create 'Buffers' folder if it doesn't exist
    buffers_folder = make_folder(intermediate_folder, "01_Buffers")

    # create network segment midpoints
    if is_verbose:
        arcpy.AddMessage("Finding network segment midpoints...")
    midpoints = arcpy.FeatureVerticesToPoints_management(seg_network_copy, scratch + "/midpoints", "MID")
    # remove unwanted fields from midpoints
    fields = arcpy.ListFields(midpoints)
    keep = ['ReachID']
    drop = []
    for field in fields:
        if not field.required and field.name not in keep and field.type != 'Geometry':
            drop.append(field.name)
    if len(drop) > 0:
        arcpy.DeleteField_management(midpoints, drop)

    if is_verbose:
        arcpy.AddMessage("Making buffers...")
    # create midpoint 100 m buffer
    midpoint_buffer = arcpy.Buffer_analysis(midpoints, scratch + "/midpoint_buffer", "100 Meters")
    # create network 30 m buffer
    buf_30m = os.path.join(buffers_folder, "buffer_30m.shp")
    arcpy.Buffer_analysis(seg_network_copy, buf_30m, "30 Meters", "", "ROUND")
    # create network 100 m buffer
    buf_100m = os.path.join(buffers_folder, "buffer_100m.shp")
    arcpy.Buffer_analysis(seg_network_copy, buf_100m, "100 Meters", "", "ROUND")

    # run geo attributes function
    arcpy.AddMessage('Adding "iGeo" attributes to network...')
    igeo_attributes(seg_network_copy, in_DEM, flow_acc, midpoint_buffer, scratch, is_verbose)

    # run vegetation attributes function
    arcpy.AddMessage('Adding "iVeg" attributes to network...')
    iveg_attributes(coded_veg, coded_hist, buf_100m, buf_30m, seg_network_copy, scratch, is_verbose)

    # find points of diversion if canals are defined
    if canal is not None:
        diversion_pts = find_points_of_diversion(canal, seg_network_copy, perennial_network, proj_path, is_verbose)
    else:
        diversion_pts = None
    
    # run ipc attributes function if conflict layers are defined by user
    if road is not None and valley_bottom is not None:
        arcpy.AddMessage('Adding "iPC" attributes to network...')
        ipc_attributes(seg_network_copy, road, railroad, canal, valley_bottom, ownership, diversion_pts, buf_30m, buf_100m, landuse, scratch, proj_path, is_verbose)

    if perennial_network is not None:
        find_is_perennial(seg_network_copy, perennial_network)

    handle_braids(seg_network_copy, canal, proj_path, find_clusters, perennial_network, is_verbose)

    # run write xml function
    arcpy.AddMessage('Writing project xml...')
    DrAr = find_dr_ar(flow_acc, in_DEM)

    trib_code_folder = os.path.dirname(os.path.abspath(__file__))
    symbology_folder = os.path.join(trib_code_folder, 'BRATSymbology')
    flow_accumulation_sym_layer = os.path.join(symbology_folder, "Flow_Accumulation.lyr")
    make_layer(os.path.dirname(DrAr), DrAr, "Flow Accumulation", symbology_layer=flow_accumulation_sym_layer, is_raster=True)

    make_layers(seg_network_copy, diversion_pts)
    write_xml(new_output_folder, coded_veg, coded_hist, seg_network, in_DEM, valley_bottom, landuse, DrAr,
              road, railroad, canal, buf_30m, buf_100m, seg_network_copy, description)

    run_tests(seg_network_copy, is_verbose)

    arcpy.CheckInExtension("spatial")


def find_is_perennial(seg_network_copy, perennial_network):
    """
    Adds the IsPerennial attribute
    :param seg_network_copy: The BRAT Table output
    :param perennial_network: The input stream network that only contains perennial networks
    :return:
    """
    arcpy.AddField_management(seg_network_copy, "IsPeren", "SHORT")
    arcpy.CalculateField_management(seg_network_copy, "IsPeren", 0, "PYTHON")

    seg_network_layer = "seg_network_lyr"
    perennial_network_layer = "perennial_network_layer"
    arcpy.MakeFeatureLayer_management(seg_network_copy, seg_network_layer)
    arcpy.MakeFeatureLayer_management(perennial_network, perennial_network_layer)

    arcpy.SelectLayerByLocation_management(seg_network_layer, "SHARE_A_LINE_SEGMENT_WITH", perennial_network_layer, '', "NEW_SELECTION")

    arcpy.CalculateField_management(seg_network_layer,"IsPeren",1,"PYTHON")


def find_dr_ar(flow_acc, in_DEM):
    """
    Finds the path to the drainage area.
    :param flow_acc: The flow accumulation raster. This may be empty
    :param in_DEM: The DEM for the entire area
    :return: The file path to the Drainage Area Raster
    """
    if flow_acc is None:
        DrArea = os.path.join(os.path.join(os.path.dirname(in_DEM), "Flow", "DrainArea_sqkm.tif"))
    else:
        DrArea = os.path.join(os.path.join(os.path.dirname(in_DEM), "Flow"), os.path.basename(flow_acc))
    return DrArea


def build_output_folder(proj_path, out_name, seg_network, road, should_segment_network, ownership, segment_by_ownership, is_verbose):
    """
    Builds the outputs folder where everything will be put
    :param proj_path: Path to the BRAT project folder.
    :param out_name: The name for the output BRAT Table.
    :param seg_network: The segmented (300m) network.
    :param road: The shapefile containing all roads for the area
    :param should_segment_network: If true, this option divides reaches based on the roads input.
    :param ownership: The shapefile contating all land ownership data for the area
    :param segment_by_ownership: The shapefile containing all land ownership data for the area
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return: The created output folder, the created intermediate folder, and the potentially segmented network
    """
    if is_verbose:
        arcpy.AddMessage("Building folder structure...")
    master_outputs_folder = os.path.join(proj_path, "Outputs")

    if not os.path.exists(master_outputs_folder):
        os.mkdir(master_outputs_folder)

    j = 1
    str_num = '01'
    new_output_folder = os.path.join(master_outputs_folder, "Output_" + str_num)
    while os.path.exists(new_output_folder):
        j += 1
        if j > 9:
            str_num = str(j)
        else:
            str_num = "0" + str(j)
        new_output_folder = os.path.join(master_outputs_folder, "Output_" + str_num)
    os.mkdir(new_output_folder)

    intermediate_folder = make_folder(new_output_folder, "01_Intermediates")

    # copy input segment network to output folder
    if out_name.endswith('.shp'):
        seg_network_copy = os.path.join(intermediate_folder, out_name)
    else:
        seg_network_copy = os.path.join(intermediate_folder, out_name + ".shp")

    # segment network by roads if should_segment_network is True
    if should_segment_network:
        segment_by_roads(seg_network, seg_network_copy, road, is_verbose)
    else:
        arcpy.CopyFeatures_management(seg_network, seg_network_copy)

    # segment network by roads if segment_by_ownership is True
    if segment_by_ownership:
        segment_network_by_ownership(seg_network_copy, ownership, is_verbose)
    else:
        pass

    return new_output_folder, intermediate_folder, seg_network_copy


def segment_by_roads(seg_network, seg_network_copy, roads, is_verbose):
    """
    Segments the seg_network by roads, and puts segmented network at seg_network_copy
    :param seg_network: Path to the seg_network that we want to segment further
    :param seg_network_copy: Path to where we want the new network to go
    :param roads: The shape file we use to segment
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return:
    """
    arcpy.AddMessage("Segmenting network by roads...")

    temp_network = os.path.join(os.path.dirname(seg_network_copy), "temp.shp")
    temp_layer = "temp_lyr"
    temp_seg_network_layer = "seg_network_lyr"

    arcpy.FeatureToLine_management([seg_network, roads], temp_network)

    arcpy.MakeFeatureLayer_management(temp_network, temp_layer)
    arcpy.MakeFeatureLayer_management(seg_network, temp_seg_network_layer)

    arcpy.SelectLayerByLocation_management(temp_layer, "WITHIN", temp_seg_network_layer)
    arcpy.CopyFeatures_management(temp_layer, seg_network_copy)

    delete_with_arcpy([temp_layer, temp_seg_network_layer, temp_network])
    add_reach_dist(seg_network, seg_network_copy, is_verbose)


def segment_network_by_ownership(seg_network_copy, ownership, is_verbose):
    """
    Segments the seg_network by ownership, and puts segmented network at seg_network_copy
    :param seg_network_copy: Path to the seg_network that we want to segment further
    :param ownership: The shape file we use to segment
    :param is_verbose: Specifies whether to provide messages
    :return:
    """
    arcpy.AddMessage("Segmenting network by ownership...")
    
    temp_seg_network_copy = os.path.join(os.path.dirname(seg_network_copy), "temp_seg_network_copy.shp")
    temp_network = os.path.join(os.path.dirname(seg_network_copy), "temp.shp")
    temp_layer = "temp_lyr"
    temp_seg_network_copy_layer = "seg_network_lyr"

    arcpy.CopyFeatures_management(seg_network_copy, temp_seg_network_copy)
    arcpy.FeatureToLine_management([seg_network_copy, ownership], temp_network)

    arcpy.MakeFeatureLayer_management(temp_network, temp_layer)
    arcpy.MakeFeatureLayer_management(seg_network_copy, temp_seg_network_copy_layer)

    arcpy.SelectLayerByLocation_management(temp_layer, "WITHIN", temp_seg_network_copy_layer)
    arcpy.CopyFeatures_management(temp_layer, seg_network_copy)
    
    add_reach_dist(temp_seg_network_copy, seg_network_copy, is_verbose)
    delete_with_arcpy([temp_layer, temp_seg_network_copy_layer, temp_network, temp_seg_network_copy])

    
def add_reach_dist(seg_network, seg_network_copy, is_verbose):
    """
    Adds reach distance field to the network
    :param seg_network: The original segmented network
    :param seg_network_copy: The copy of the segmented network created by build_output_folder
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return:
    """
    if is_verbose:
        arcpy.AddMessage("Calculating ReachDist...")

    fields = [f.name for f in arcpy.ListFields(seg_network_copy)]
    if 'ReachID' in fields:
        with arcpy.da.UpdateCursor(seg_network_copy, ['FID', 'ReachID']) as cursor:
            for row in cursor:
                row[1] = row[0]
                cursor.updateRow(row)

    # get distance along route (LineID) for segment midpoints
    midpoints = arcpy.FeatureVerticesToPoints_management(seg_network_copy, 'in_memory/midpoints', "MID")

    seg_network_dissolve = arcpy.Dissolve_management(seg_network, 'in_memory/seg_network_dissolve', 'StreamID', '',
                                                     'SINGLE_PART', 'UNSPLIT_LINES')

    arcpy.AddField_management(seg_network_dissolve, 'From_', 'DOUBLE')
    arcpy.AddField_management(seg_network_dissolve, 'To_', 'DOUBLE')
    with arcpy.da.UpdateCursor(seg_network_dissolve, ['SHAPE@Length', 'From_', 'To_']) as cursor:
        for row in cursor:
            row[1] = 0.0
            row[2] = row[0]
            cursor.updateRow(row)

    arcpy.CreateRoutes_lr(seg_network_dissolve, 'StreamID', 'in_memory/flowline_route', 'TWO_FIELDS', 'From_', 'To_')
    route_tbl = arcpy.LocateFeaturesAlongRoutes_lr(midpoints, 'in_memory/flowline_route', 'StreamID',
                                                  1.0,
                                                  os.path.join(os.path.dirname(seg_network_copy), 'tbl_Routes.dbf'),
                                                  'RID POINT MEAS')

    dist_dict = {}
    # add reach id distance values to dictionary
    with arcpy.da.SearchCursor(route_tbl, ['ReachID', 'MEAS']) as cursor:
        for row in cursor:
            dist_dict[row[0]] = row[1]

    # populate dictionary value to output field by ReachID
    arcpy.AddField_management(seg_network_copy, 'ReachDist', 'DOUBLE')
    with arcpy.da.UpdateCursor(seg_network_copy, ['ReachID', 'ReachDist']) as cursor:
        for row in cursor:
            aKey = row[0]
            row[1] = dist_dict[aKey]
            cursor.updateRow(row)

    arcpy.Delete_management('in_memory')



def zonalStatsWithinBuffer(buffer, ras, stat_type, stat_field, out_fc, out_FC_field, scratch):
    """
    Calculate zonal statistics within buffer function
    :param buffer: The buffer around the stream
    :param ras: The DEM raster
    :param stat_type: The type of statistic to be calculated (MAXIMUM, MINIMUM, etc.)
    :param stat_field: The name of the field containing statistics to be calculated
    :param out_fc: The feature class to output to.
    :param out_FC_field: The field within the output feature class to output to.
    :param scratch: The current workspace
    :return:
    """
    # get input raster stat value within each buffer
    # note: zonal stats as table does not support overlapping polygons so we will check which
    #       reach buffers output was produced for and which we need to run tool on again
    stat_tbl = arcpy.sa.ZonalStatisticsAsTable(buffer, 'ReachID', ras, os.path.join(scratch, 'statTbl'), 'DATA', stat_type)

    # get list of segment buffers where zonal stats tool produced output
    have_stat_list = [row[0] for row in arcpy.da.SearchCursor(stat_tbl, 'ReachID')]
    # create dictionary to hold all reach buffer min dem z values
    stat_dict = {}
    # add buffer raster stat values to dictionary
    with arcpy.da.SearchCursor(stat_tbl, ['ReachID', stat_field]) as cursor:
        for row in cursor:
            stat_dict[row[0]] = row[1]
    # create list of overlapping buffer reaches (i.e., where zonal stats tool did not produce output)
    need_stat_list = []
    with arcpy.da.SearchCursor(buffer, ['ReachID']) as cursor:
        for row in cursor:
            if row[0] not in have_stat_list:
                need_stat_list.append(row[0])
    # run zonal stats until we have output for each overlapping buffer segment
    stat = None
    tmp_buff_lyr = None
    num_broken_repetitions = 0
    BROKEN_REPS_ALLOWED = 5
    while len(need_stat_list) > 0:
        # create tuple of segment ids where still need raster values
        need_stat = ()
        for reach in need_stat_list:
            if reach not in need_stat:
                need_stat += (reach,)
        # use the segment id tuple to create selection query and run zonal stats tool
        if len(need_stat) == 1:
            quer = '"ReachID" = ' + str(need_stat[0])
        else:
            quer = '"ReachID" IN ' + str(need_stat)
        tmp_buff_lyr = arcpy.MakeFeatureLayer_management(buffer, 'tmp_buff_lyr')
        arcpy.SelectLayerByAttribute_management(tmp_buff_lyr, 'NEW_SELECTION', quer)
        stat = arcpy.sa.ZonalStatisticsAsTable(tmp_buff_lyr, 'ReachID', ras, os.path.join(scratch, 'stat'), 'DATA', stat_type)
        # add segment stat values from zonal stats table to main dictionary
        with arcpy.da.SearchCursor(stat, ['ReachID', stat_field]) as cursor:
            for row in cursor:
                stat_dict[row[0]] = row[1]
        # create list of reaches that were run and remove from 'need to run' list
        have_stat_list2 = [row[0] for row in arcpy.da.SearchCursor(stat, 'ReachID')]

        if len(have_stat_list2) == 0:
            num_broken_repetitions += 1
            if num_broken_repetitions >= BROKEN_REPS_ALLOWED:
                warning_message = "While calculating " + out_FC_field + ", the tool ran into an error. The following "
                warning_message += "ReachIDs did not recieve correct values:\n"
                for reach_id in need_stat_list:
                    if reach_id == need_stat_list[-1]:
                        warning_message += "and "
                    warning_message += str(reach_id)
                    if reach_id != need_stat_list[-1]:
                        warning_message += ", "
                warning_message += "\n"
                arcpy.AddWarning(warning_message)
                for reach_id in need_stat_list:
                    stat_dict[reach_id] = 0
                need_stat_list = []
        for reach in have_stat_list2:
            need_stat_list.remove(reach)

    # populate dictionary value to output field by ReachID
    with arcpy.da.UpdateCursor(out_fc, ['ReachID', out_FC_field]) as cursor:
        for row in cursor:
            try:
                aKey = row[0]
                row[1] = stat_dict[aKey]
                cursor.updateRow(row)
            except:
                pass
    stat_dict.clear()

    # delete temp fcs, tbls, etc.
    #items = [statTbl, haveStatList, haveStatList2, needStatList, stat, tmp_buff_lyr, needStat]
    items = [stat_tbl, stat, tmp_buff_lyr]
    for item in items:
        if item is not None:
            arcpy.Delete_management(item)



def igeo_attributes(out_network, in_DEM, flow_acc, midpoint_buffer, scratch, is_verbose):
    """
    calculates min and max elevation, length, slope, and drainage area for each flowline segment
    :param out_network: The output netwrok to add fields to.
    :param in_DEM: The DEM raster.
    :param flow_acc: Th eflow accumulation raster
    :param midpoint_buffer: The buffer created from midpoints
    :param scratch: The current workspace
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return: Drainage Area
    """
    # if fields already exist, delete them
    fields = [f.name for f in arcpy.ListFields(out_network)]
    drop = ["iGeo_ElMax", "iGeo_ElMin", "iGeo_Len", "iGeo_Slope", "iGeo_DA"]
    for field in fields:
        if field in drop:
            arcpy.DeleteField_management(out_network, field)

    # add flowline segment id field ('ReachID') for more 'stable' joining
    if 'ReachID' not in fields:
        arcpy.AddField_management(out_network, 'ReachID', 'LONG')
        with arcpy.da.UpdateCursor(out_network, ['FID', 'ReachID']) as cursor:
            for row in cursor:
                row[1] = row[0]
                cursor.updateRow(row)
    if is_verbose:
        arcpy.AddMessage("Preprocessing DEM...")
    #  --smooth input dem by 3x3 cell window--
    #  define raster environment settings
    desc = arcpy.Describe(in_DEM)
    arcpy.env.extent = desc.Extent
    arcpy.env.outputCoordinateSystem = desc.SpatialReference
    arcpy.env.cellSize = desc.meanCellWidth
    # calculate mean z over 3x3 cell window
    neighborhood = NbrRectangle(3, 3, "CELL")
    tmp_dem = FocalStatistics(in_DEM, neighborhood, 'MEAN')
    # clip smoothed dem to input dem
    DEM = ExtractByMask(tmp_dem, in_DEM)

    # function to attribute start/end elevation (dem z) to each flowline segment
    def zSeg(vertex_type, out_field):
        if is_verbose:
            arcpy.AddMessage("Calculating values for " + out_field + "...")
        # create start/end points for each flowline reach segment
        tmp_pts = os.path.join(scratch, 'tmp_pts')
        arcpy.FeatureVerticesToPoints_management(out_network, tmp_pts, vertex_type)
        # create 30 meter buffer around each start/end point
        tmp_buff = os.path.join(scratch, 'tmp_buff')
        arcpy.Buffer_analysis(tmp_pts, tmp_buff, '30 Meters')
        # get min dem z value within each buffer
        arcpy.AddField_management(out_network, out_field, "DOUBLE")
        zonalStatsWithinBuffer(tmp_buff, DEM, 'MINIMUM', 'MIN', out_network, out_field, scratch)

        # delete temp fcs, tbls, etc.
        items = [tmp_pts, tmp_buff]
        for item in items:
            arcpy.Delete_management(item)

    # run zSeg function for start/end of each network segment
    zSeg('START', 'iGeo_ElMax')
    zSeg('END', 'iGeo_ElMin')

    # calculate network reach slope
    arcpy.AddField_management(out_network, "iGeo_Len", "DOUBLE")
    arcpy.CalculateField_management(out_network, "iGeo_Len", '!shape.length@meters!', "PYTHON_9.3")
    arcpy.AddField_management(out_network, "iGeo_Slope", "DOUBLE")
    with arcpy.da.UpdateCursor(out_network, ["iGeo_ElMax", "iGeo_ElMin", "iGeo_Len", "iGeo_Slope"]) as cursor:
        if is_verbose:
            arcpy.AddMessage("Calculating iGeo_Slope...")
        for row in cursor:
            if row[2] == 0:
                row[3] = 0.0001
            else:
                row[3] = (abs(row[0] - row[1]))/row[2]
            if row[3] == 0.0:
                row[3] = 0.0001
            cursor.updateRow(row)

    # get DA values
    if flow_acc is None:
        arcpy.AddMessage("Calculating drainage area...")
        calc_drain_area(DEM, in_DEM)
    elif not os.path.exists(os.path.dirname(in_DEM) + "/Flow"): # if there's no folder for the flow accumulation, make one
        os.mkdir(os.path.dirname(in_DEM) + "/Flow")
        if is_verbose:
            arcpy.AddMessage("Copying drainage area raster...")
        arcpy.CopyRaster_management(flow_acc, os.path.dirname(in_DEM) + "/Flow/" + os.path.basename(flow_acc))

    DrArea = find_dr_ar(flow_acc, in_DEM)
    # Todo: check this bc it seems wrong to pull from midpoint buffer

    # add drainage area 'iGeo_DA' field to flowline network
    arcpy.AddField_management(out_network, "iGeo_DA", "DOUBLE")
    # get max drainage area within 100 m midpoint buffer
    if is_verbose:
        arcpy.AddMessage("Calculating iGeo_DA...")
    zonalStatsWithinBuffer(midpoint_buffer, DrArea, "MAXIMUM", 'MAX', out_network, "iGeo_DA", scratch)

    # replace '0' drainage area values with tiny value
    with arcpy.da.UpdateCursor(out_network, ["iGeo_DA"]) as cursor:
        for row in cursor:
            if row[0] == 0:
                row[0] = 0.00000001
            cursor.updateRow(row)

    return DrArea


def iveg_attributes(coded_veg, coded_hist, buf_100m, buf_30m, out_network, scratch, is_verbose):
    """
    Calculates both existing and potential mean vegetation value within 30 m and 100 m buffer of each stream segment
    :param coded_veg: The coded existing vegetation raster
    :param coded_hist: The coded historic vegetation raster
    :param buf_100m: The 100m stream buffer
    :param buf_30m: The 30m stream buffer
    :param out_network: The output network that data will be added to.
    :param scratch: The current workspace
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return:
    """
    # if fields already exist, delete them
    fields = [f.name for f in arcpy.ListFields(out_network)]
    drop = ["iVeg_100EX", "iVeg_30EX", "iVeg100Hpe", "iVeg_30Hpe"]
    for field in fields:
        if field in drop:
            arcpy.DeleteField_management(out_network, field)

    # --existing vegetation values--
    if is_verbose:
        arcpy.AddMessage("Creating current veg lookup raster...")
    veg_lookup = Lookup(coded_veg, "VEG_CODE")
    # add mean veg value 'iVeg100EX' field to flowline network
    arcpy.AddField_management(out_network, "iVeg100EX", "DOUBLE")
    # get mean existing veg value within 100 m buffer
    if is_verbose:
        arcpy.AddMessage("Calculating iVeg100EX...")
    zonalStatsWithinBuffer(buf_100m, veg_lookup, 'MEAN', 'MEAN', out_network, "iVeg100EX", scratch)

    # add mean veg value 'iVeg_VT30EX' field to flowline network
    arcpy.AddField_management(out_network, "iVeg_30EX", "DOUBLE")
    # get mean existing veg value within 30 m buffer
    if is_verbose:
        arcpy.AddMessage("Calculating iVeg_30EX...")
    zonalStatsWithinBuffer(buf_30m, veg_lookup, 'MEAN', 'MEAN', out_network, "iVeg_30EX", scratch)

    # delete temp fcs, tbls, etc.
    items = [veg_lookup]
    for item in items:
        arcpy.Delete_management(item)

    # --historic (i.e., potential) vegetation values--
    if is_verbose:
        arcpy.AddMessage("Creating historic veg lookup raster...")
    hist_veg_lookup = Lookup(coded_hist, "VEG_CODE")

    # add mean veg value 'iVeg100Hpe' field to flowline network
    arcpy.AddField_management(out_network, "iVeg100Hpe", "DOUBLE")
    # get mean potential veg value within 100 m buffer
    if is_verbose:
        arcpy.AddMessage("Calculating iVeg100Hpe...")
    zonalStatsWithinBuffer(buf_100m, hist_veg_lookup, 'MEAN', 'MEAN', out_network, "iVeg100Hpe", scratch)

    # add mean veg value 'iVeg_30Hpe' field to flowline network
    arcpy.AddField_management(out_network, "iVeg_30Hpe", "DOUBLE")
    # get mean potential veg value within 30 m buffer
    if is_verbose:
        arcpy.AddMessage("Calculating iVeg_30Hpe...")
    zonalStatsWithinBuffer(buf_30m, hist_veg_lookup, 'MEAN', 'MEAN', out_network, "iVeg_30Hpe", scratch)

    # delete temp fcs, tbls, etc.
    items = [hist_veg_lookup]
    for item in items:
        arcpy.Delete_management(item)


def find_points_of_diversion(canal, network, perennial_network, proj_path, is_verbose):
    """
    Finds potential points where water is being diverted into canals from the stream network by finding intersections between the canal and network
    :param: canal: input canals network
    :param: network: input stream network
    :param: perennial_network: input perennial stream network, will be used preferentially to the full network
    :param: is verbose: True/False for whether to return messages in ArcMap
    :return: points of diversion, the points where the canals and network intersect
    """
    # find temp directory, or make if not present
    temp_dir = os.path.join(proj_path, 'Temp')
    if not os.path.exists(temp_dir):
        make_temp_dir(proj_path, is_verbose)
        
    # find points of diversion (intersection between perennial stream and canals
    if is_verbose:
        arcpy.AddMessage("Finding points of diversion...")

    # name output and place in canals folder
    canal_folder = os.path.dirname(canal)
    diversion_points = canal_folder + "\\points_of_diversion.shp"

    if not os.path.exists(diversion_points):
        # dissolve canals into single feature
        canal_dissolve = temp_dir + "\\canals_dissolved.shp"
        arcpy.Dissolve_management(canal, canal_dissolve, '', '', 'SINGLE_PART', 'UNSPLIT_LINES')# dissolve canals into single feature

        # intersect canals with perennial network if available
        if perennial_network is not None:
            arcpy.Intersect_analysis([perennial_network, canal_dissolve], diversion_points, "", 12, "POINT")

        # else intersect canals with full network minus the canals
        else:
            # select reaches that do NOT overlap with canals and save to temp_network_no_canals_shp    
            temp_network_no_canals_lyr = arcpy.MakeFeatureLayer_management(network, 'temp_network_no_canals_lyr')
            arcpy.SelectLayerByLocation_management(in_layer=temp_network_no_canals_lyr, overlap_type='HAVE_THEIR_CENTER_IN', select_features=canal_dissolve, search_distance=5, selection_type='NEW_SELECTION')
            arcpy.SelectLayerByAttribute_management(temp_network_no_canals_lyr, 'SWITCH_SELECTION')
            # save temp network without canals to temp directory
            temp_network_no_canals_shp = os.path.join(temp_dir, "network_no_canals.shp")
            arcpy.CopyFeatures_management(temp_network_no_canals_lyr, temp_network_no_canals_shp)
            # find intersection between network without canals and canals
            arcpy.Intersect_analysis([temp_network_no_canals_shp, canal_dissolve], diversion_points, "", 12, "POINT")

    # return new diversion points shapefile
    return diversion_points

        

def ipc_attributes(out_network, road, railroad, canal, valley_bottom, ownership, diversion_points, buf_30m, buf_100m, landuse, scratch, proj_path, is_verbose):
    """
    Calculates distances from road intersections, adjacent roads, railroads and canals for each flowline segment
    :param out_network: The output network where fields will be added
    :param road: The roads shapefile for the entire area
    :param railroad: The railroads shapefile for the entire area
    :param canal: The canals shapefile for the entire area
    :param valley_bottom: The valley bottom shapefile for the entire area
    :param ownership: The land ownership shapefile for the entire area
    :param buf_30m: The 30m stream buffer
    :param buf_100m: The 100m stream buffer
    :param landuse: The landuse raster
    :param scratch: The current workspace
    :param projPath: The file path to the project folder
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :param perennial_network: The perennial network shapefile
    :return:
    """
    # find temp directory, or make if not present
    temp_dir = os.path.join(proj_path, 'Temp')
    if not os.path.exists(temp_dir):
        make_temp_dir(proj_path, is_verbose)
        
    # if fields already exist, delete them
    fields = [f.name for f in arcpy.ListFields(out_network)]
    drop = ["iPC_RoadX", "iPC_Road", "iPC_RoadVB", "iPC_Rail", "iPC_RailVB", "iPC_Canal", "iPC_DivPts", "iPC_LU", "iPC_Privat", "ADMIN_AGEN"]
    for field in fields:
        if field in drop:
            arcpy.DeleteField_management(out_network, field)

    # calculate mean distance from road-stream crossings ('iPC_RoadX'), roads ('iPC_Road') and roads clipped to the valley bottom ('iPC_RoadVB')
    if road is not None:
        road_crossings = temp_dir + "\\roadx.shp"
        # create points at road-stream intersections
        arcpy.Intersect_analysis([out_network, road], road_crossings, "", "", "POINT")
        find_distance_from_feature(out_network, road_crossings, valley_bottom, temp_dir, buf_30m, "roadx", "iPC_RoadX", scratch, is_verbose, clip_feature = False)

    if road is not None:
        find_distance_from_feature(out_network, road, valley_bottom, temp_dir, buf_30m, "roadvb", "iPC_RoadVB", scratch, is_verbose, clip_feature = True)
        find_distance_from_feature(out_network, road, valley_bottom, temp_dir, buf_30m, "road", "iPC_Road", scratch, is_verbose, clip_feature = False)

    if railroad is not None:
        find_distance_from_feature(out_network, railroad, valley_bottom, temp_dir, buf_30m, "railroadvb", "iPC_RailVB", scratch, is_verbose, clip_feature = True)
        find_distance_from_feature(out_network, railroad, valley_bottom, temp_dir, buf_30m, "railroad", "iPC_Rail", scratch, is_verbose, clip_feature = False)

    if canal is not None:
        # find distance from canal
        find_distance_from_feature(out_network, canal, valley_bottom, temp_dir, buf_30m, "canal", "iPC_Canal", scratch, is_verbose, clip_feature=False)
    if diversion_points is not None:
        # calculate distance from points of diversion
        find_distance_from_feature(out_network, diversion_points, valley_bottom, temp_dir, buf_30m, "diversion", "iPC_DivPts", scratch, is_verbose, clip_feature = False)

    # assign land ownership agency to each reach
    if ownership is not None:
        if is_verbose:
            arcpy.AddMessage('Assigning land ownership to each reach...')
        spatial_join_temp = temp_dir + "\\ownership_network_join.shp"
        if os.path.exists(spatial_join_temp):
            arcpy.Delete_management(spatial_join_temp)
        ownership_fields = [f.name for f in arcpy.ListFields(ownership)]
        network_fields = [f.name for f in arcpy.ListFields(out_network)]
        if 'FID' in network_fields:
            network_fields.remove('FID')
        if 'Shape' in network_fields:
            network_fields.remove('Shape')
        for field in ownership_fields:
            if field in network_fields:
                arcpy.DeleteField_management(out_network, str(field)) 
        arcpy.SpatialJoin_analysis(out_network, ownership, spatial_join_temp, 'JOIN_ONE_TO_ONE', 'KEEP_ALL', match_option = 'HAVE_THEIR_CENTER_IN')           
        arcpy.JoinField_management(in_data=out_network, in_field='FID', join_table=spatial_join_temp, join_field='FID', fields='ADMIN_AGEN')
        with arcpy.da.UpdateCursor(out_network, 'ADMIN_AGEN') as cursor:
            for row in cursor:
                if row[0] == ' ':
                    row[0] = 'None'
                cursor.updateRow(row)

        # calculate minimum distance from private or undetermined land ownership('iPC_Privat') 
        private = temp_dir + "\\private_land.shp"
        private_lyr = arcpy.MakeFeatureLayer_management(ownership, "private_lyr")
        arcpy.SelectLayerByAttribute_management(private_lyr, 'NEW_SELECTION', """ "ADMIN_AGEN" = 'PVT' OR "ADMIN_AGEN" = 'UND' """)
        arcpy.CopyFeatures_management(private_lyr, private)
        find_distance_from_feature(out_network, private, valley_bottom, temp_dir, buf_30m, "private_land", "iPC_Privat", scratch, is_verbose, clip_feature=False)
    
    # calculate mean landuse value ('iPC_LU')
    if landuse is not None:
        add_landuse_to_table(out_network, landuse, buf_100m, scratch, is_verbose)

    add_min_distance(out_network)

    # clear the environment extent setting
    arcpy.ClearEnvironment("extent")


def make_temp_dir(projPath, is_verbose):
    """
    Creates a temporary directory
    :param projPath: The file path to the project folder
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return:
    """
    if is_verbose:
        arcpy.AddMessage("Deleting and remaking temp dir...")
    from shutil import rmtree
    temp_dir = os.path.join(projPath, 'Temp')
    if os.path.exists(temp_dir):
        rmtree(temp_dir)
    os.mkdir(temp_dir)

    
def add_min_distance(out_network):
    """
    Adds oPC_Dist field, and populated it with the minimum distance from multiple features
    :param out_network: The output network where fields will be added
    :return:
    """
    arcpy.AddField_management(out_network, "oPC_Dist", 'DOUBLE')
    fields = [f.name for f in arcpy.ListFields(out_network)]
    all_dist_fields = ["oPC_Dist", "iPC_RoadX", "iPC_RoadVB", "iPC_RailVB", "iPC_Canal", "iPC_DivPts"]
    dist_fields = []
    for field in all_dist_fields:
        if field in fields:
            dist_fields.append(field)
    with arcpy.da.UpdateCursor(out_network, dist_fields) as cursor:
        for row in cursor:
            row[0] = min(row[1:])
            cursor.updateRow(row)


def add_landuse_to_table(out_network, landuse, buf_100m, scratch, is_verbose):
    """
    Adds landuse fields to the output network[iPC_LU, "iPC_VLowLU", "iPC_LowLU", "iPC_ModLU", "iPC_HighLU"]
    :param out_network: Output network to add fields to.
    :param landuse: The landuse raster.
    :param buf_100m: The 100m stream buffer
    :param scratch: Th current workspace
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return:
    """
    if is_verbose:
        arcpy.AddMessage("Calculating iPC_LU values...")
    arcpy.AddField_management(out_network, "iPC_LU", "DOUBLE")
    # create raster with just landuse code values
    lu_ras = Lookup(landuse, "LU_CODE")
    # calculate mean landuse value within 100 m buffer of each network segment
    zonalStatsWithinBuffer(buf_100m, lu_ras, 'MEAN', 'MEAN', out_network, "iPC_LU", scratch)
    # get percentage of each land use class in 100 m buffer of stream segment
    fields = [f.name.upper() for f in arcpy.ListFields(landuse)]

    if "LUI_CLASS" not in fields:
        arcpy.AddWarning("No field named \"LU_CLASS\" in the land use raster. Make sure that this field exists" +
                         " with no typos if you wish to use the data from the land use raster")
        return

    buf_fields = [f.name for f in arcpy.ListFields(buf_100m)]
    if 'oArea' not in buf_fields:
        arcpy.AddField_management(buf_100m, 'oArea', 'DOUBLE')
        with arcpy.da.UpdateCursor(buf_100m, ['SHAPE@AREA', 'oArea']) as cursor:
            for row in cursor:
                row[1] = row[0]
                cursor.updateRow(row)
    landuse_poly = arcpy.RasterToPolygon_conversion(landuse, os.path.join(scratch, 'landuse_poly'), 'NO_SIMPLIFY', "LUI_Class")
    landuse_int = arcpy.Intersect_analysis([landuse_poly, buf_100m], os.path.join(scratch, 'landuse_int'))
    arcpy.AddField_management(landuse_int, 'propArea', 'DOUBLE')
    with arcpy.da.UpdateCursor(landuse_int, ['SHAPE@AREA', 'oArea', 'propArea']) as cursor:
        for row in cursor:
            row[2] = row[0]/row[1]
            cursor.updateRow(row)
    area_tbl = arcpy.Statistics_analysis(landuse_int, os.path.join(scratch, 'areaTbl'), [['propArea', 'SUM']], ['ReachID', 'LUI_CLASS'])
    area_piv_tbl = arcpy.PivotTable_management(area_tbl, ['ReachID'], 'LUI_CLASS', 'SUM_propArea', os.path.join(scratch, 'areaPivTbl'))

    sanitize_area_piv_tbl(area_piv_tbl)
    # create empty dictionary to hold input table field values
    tbl_dict = {}
    # add values to dictionary
    with arcpy.da.SearchCursor(area_piv_tbl, ['ReachID', 'VeryLow', 'Low', 'Moderate', 'High']) as cursor:
        for row in cursor:
            tbl_dict[row[0]] = [row[1], row[2], row[3], row[4]]

    # populate flowline network out fields
    arcpy.AddField_management(out_network, "iPC_VLowLU", 'DOUBLE')
    arcpy.AddField_management(out_network, "iPC_LowLU", 'DOUBLE')
    arcpy.AddField_management(out_network, "iPC_ModLU", 'DOUBLE')
    arcpy.AddField_management(out_network, "iPC_HighLU", 'DOUBLE')

    with arcpy.da.UpdateCursor(out_network, ['ReachID', 'iPC_VLowLU', 'iPC_LowLU', 'iPC_ModLU', 'iPC_HighLU']) as cursor:
        for row in cursor:
            try:
                aKey = row[0]
                row[1] = round(100*tbl_dict[aKey][0], 2)
                row[2] = round(100*tbl_dict[aKey][1], 2)
                row[3] = round(100*tbl_dict[aKey][2], 2)
                row[4] = round(100*tbl_dict[aKey][3], 2)
                cursor.updateRow(row)
            except:
                pass
    tbl_dict.clear()

    arcpy.Delete_management(lu_ras)


def sanitize_area_piv_tbl(area_piv_tbl):
    """
    Makes sure that the areaPivTbl has all the fields we need. If it doesn't, we'll add it.
    :param area_piv_tbl:
    :return:
    """
    fields = [f.name for f in arcpy.ListFields(area_piv_tbl)]
    check_and_add_zero_fields(area_piv_tbl, fields, 'VeryLow')
    check_and_add_zero_fields(area_piv_tbl, fields, 'Low')
    check_and_add_zero_fields(area_piv_tbl, fields, 'Moderate')
    check_and_add_zero_fields(area_piv_tbl, fields, 'High')


def check_and_add_zero_fields(table, fields, field_name):
    """
    Checks that a field is in the table. If it isn't, we add it and populate it with zeros
    :param table: The table that we want to check
    :param fields: All the fields in the table (more efficient if doing multiple checks)
    :param field_name: The name of the field we want to check for
    :return:
    """
    if field_name not in fields:
        arcpy.AddField_management(table, field_name, "DOUBLE")
        arcpy.CalculateField_management(table, field_name, 0, "PYTHON")


def find_distance_from_feature(out_network, feature, valley_bottom, temp_dir, buf, temp_name, new_field_name, scratch, is_verbose, clip_feature = False):
    """
    Finds the distance from a given feature to each stream segment and populates a new field
    :param out_network: The output network where new fields will be added
    :param feature: The feature that you want to calculate the distance from
    :param valley_bottom: The valley bottom shapefile
    :param temp_dir: The temporary folder directory
    :param buf: The 30m stream buffer shapefile
    :param temp_name: The name given to the temporary shapefile created
    :param new_field_name: The name of the new field to be added to the output
    :param scratch: The current workspace
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :param clip_feature: If true, the feature will be clipped to the valley bottom
    :return:
    """
    if is_verbose:
        arcpy.AddMessage("Calculating " + new_field_name + " values...")
    arcpy.AddField_management(out_network, new_field_name, "DOUBLE")

    if clip_feature == True:
        # clip input feature to the valley bottom
        feature_subset = arcpy.Clip_analysis(feature, valley_bottom, os.path.join(temp_dir, temp_name + '_subset.shp'))
        # convert feature for count purposes
        feature_mts = arcpy.MultipartToSinglepart_management(feature_subset, os.path.join(temp_dir, temp_name + "_mts.shp"))
    else:
        feature_mts = arcpy.MultipartToSinglepart_management(feature, os.path.join(temp_dir, temp_name + "_mts.shp"))
        feature_subset = feature

    count = arcpy.GetCount_management(feature_mts)
    ct = int(count.getOutput(0))
    # if there are features, then set the distance from to high value (10000 m)
    if ct < 1:
        if is_verbose:
            arcpy.AddMessage('No Data found for ' + new_field_name)
        with arcpy.da.UpdateCursor(out_network, new_field_name) as cursor:
            for row in cursor:
                row[0] = 10000.0
                cursor.updateRow(row)
    # if there are features, calculate distance
    else:
        # set extent to the stream network
        arcpy.env.extent = out_network
        # calculate euclidean distance from input features

        sr = arcpy.Describe(feature_subset).spatialReference
        unit = sr.linearUnitName
        arcpy.AddMessage('Raster units are ' + unit)

        ed_feature = EucDistance(feature_subset, cell_size = 5) # cell size of 5 m
        # get min distance from feature in the within 30 m buffer of each network segment
        if new_field_name == 'iPC_RoadX':
            zonalStatsWithinBuffer(buf, ed_feature, 'MINIMUM', 'MIN', out_network, new_field_name, scratch)
        else:
            zonalStatsWithinBuffer(buf, ed_feature, 'MEAN', 'MEAN', out_network, new_field_name, scratch)

        # delete temp fcs, tbls, etc.
        items = []
        for item in items:
            arcpy.Delete_management(item)

# calculate drainage area function
def calc_drain_area(DEM, input_DEM):
    """
    Calculate drainage area function
    :param DEM: Smoothed DEM
    :param input_DEM: The original input DEM
    :return:
    """
    #  define raster environment settings
    desc = arcpy.Describe(DEM)
    arcpy.env.extent = desc.Extent
    arcpy.env.outputCoordinateSystem = desc.SpatialReference
    arcpy.env.cellSize = desc.meanCellWidth

    #  calculate cell area for use in drainage area calcultion
    height = desc.meanCellHeight
    width = desc.meanCellWidth
    cell_area = height * width

    # derive drainage area raster (in square km) from input DEM
    # note: draiange area calculation assumes input dem is in meters
    filled_DEM = Fill(DEM) # fill sinks in dem
    flow_direction = FlowDirection(filled_DEM) # calculate flow direction
    flow_accumulation = FlowAccumulation(flow_direction) # calculate flow accumulation
    drain_area = flow_accumulation * cell_area / 1000000 # calculate drainage area in square kilometers

    # save drainage area raster
    if os.path.exists(os.path.dirname(input_DEM) + "/Flow/DrainArea_sqkm.tif"):
        arcpy.Delete_management(os.path.dirname(input_DEM) + "/Flow/DrainArea_sqkm.tif")
        arcpy.CopyRaster_management(drain_area, os.path.dirname(input_DEM) + "/Flow/DrainArea_sqkm.tif")
    else:
        os.mkdir(os.path.dirname(input_DEM) + "/Flow")
        arcpy.CopyRaster_management(drain_area, os.path.dirname(input_DEM) + "/Flow/DrainArea_sqkm.tif")


def write_xml(output_folder, coded_veg, coded_hist, seg_network, inDEM, valley_bottom, landuse,
              DrAr, road, railroad, canal, buf_30m, buf_100m, out_network, description):
    """
    Writes the xml file for the project
    :param output_folder: The folder where everything will be output
    :param coded_veg: The landfire EVT layer
    :param coded_hist: The landfire BPS layer
    :param seg_network: The segmented (300m) network
    :param inDEM: The DEM for the entire project
    :param valley_bottom: The valley bottom shapefile
    :param landuse: The landuse raster
    :param DrAr: The drainage area raster
    :param road: The roads shapefile
    :param railroad: The railroads shapefile
    :param canal: The canals shapefile
    :param buf_30m: The 30m buffer shapefile
    :param buf_100m: The 100m buffer shapefile
    :param out_network: The network that new data has been added to
    :param description: A short description of the run that will be added to the XML
    :return:
    """
    proj_path = os.path.dirname(os.path.dirname(output_folder))
    output_folder_num = str(int(output_folder[-2:]))
    xml_file_path = proj_path + "/project.rs.xml"

    if not os.path.exists(xml_file_path):
        arcpy.AddWarning("XML file not found. Could not update XML file")
        return

    xml_file = XMLBuilder(xml_file_path)

    add_drain_area_to_inputs_xml(xml_file, DrAr, proj_path)

    realizations_element = xml_file.find("Realizations")
    if realizations_element is None:
        realizations_element = xml_file.add_sub_element(xml_file.root, "Realizations")

    creation_time = datetime.datetime.today().isoformat()
    brat_element = xml_file.add_sub_element(realizations_element, "BRAT", tags=[("dateCreated", creation_time),
                                                                                ("guid", getUUID()),
                                                                                ("id", "RZ" + output_folder_num),
                                                                                ("ProductVersion", "3.0.21")])
    xml_file.add_sub_element(brat_element, "Name", "BRAT Realization " + output_folder_num)

    meta_element = xml_file.add_sub_element(brat_element, "MetaData")

    write_description(xml_file, meta_element, description)

    write_input_xml(xml_file, brat_element, proj_path, coded_veg, coded_hist, landuse, valley_bottom, road, railroad,
                    canal, inDEM, DrAr, seg_network, buf_30m, buf_100m)

    write_intermediate_xml(xml_file, brat_element, proj_path, out_network)

    xml_file.write()


def write_description(xml_file, meta_element, description):
    """
    Writes the description to the XML
    :param xml_file: The XML file to write to.
    :param meta_element: The current meta element
    :param description: A short description of the run that will be added to the XML
    :return:
    """
    if description is None:
        xml_file.add_sub_element(meta_element, "Description")
    elif len(description) <= 100:
        xml_file.add_sub_element(meta_element, "Meta", description, tags=[("name", "description")])
    elif len(description) > 100:
        raise Exception("Description must be less than 100 characters")



def write_intermediate_xml(xml_file, brat_element, proj_path, out_network):
    """
    Writes part of the XML file for all intermediate data.
    :param xml_file: The XML file to write to.
    :param brat_element: The XML element containing BRAT data.
    :param proj_path: The file path to the project folder.
    :param out_network: The output network that new data has been added to.
    :return:
    """
    intermediates_element = xml_file.add_sub_element(brat_element, "Intermediates")
    intermediate_element = xml_file.add_sub_element(intermediates_element, "Intermediate")

    xml_file.add_sub_element(intermediate_element, "Name", "BRAT Intermediate")
    write_xml_element_with_path(xml_file, intermediate_element, "Vector", "BRAT Input Table", out_network, proj_path)



def write_input_xml(xml_file, brat_element, proj_path, coded_veg, coded_hist, landuse, valley_bottom, road, railroad,
                    canal, inDEM, DrAr, seg_network, buf_30m, buf_100m):
    """
    Writes part of the XML file for all input data.
    :param xml_file: The XML file to write to.
    :param brat_element: The XML element containing BRAT data.
    :param proj_path: The file path to the project folder.
    :param coded_veg: The landfire EVT layer
    :param coded_hist: The landfire BPS layer
    :param landuse: The landuse raster
    :param valley_bottom: The valley bottom shapefile
    :param road: The roads shapefile
    :param railroad: The railroads shapefile
    :param canal: The canals shapefile
    :param inDEM: The DEM for the entire project
    :param DrAr: The drainage area raster
    :param seg_network: The segmented (300m) network
    :param buf_30m: The 30m buffer shapefile
    :param buf_100m: The 100m buffer shapefile
    :return:
    """
    inputs_element = xml_file.add_sub_element(brat_element, "Inputs")

    add_input_ref_element(xml_file, proj_path, inputs_element, coded_veg, "ExistingVegetation")
    add_input_ref_element(xml_file, proj_path, inputs_element, coded_hist, "HistoricVegetation")
    add_input_ref_element(xml_file, proj_path, inputs_element, landuse, "LandUse")
    add_input_ref_element(xml_file, proj_path, inputs_element, valley_bottom, "ValleyBottom")
    add_input_ref_element(xml_file, proj_path, inputs_element, road, "Roads")
    add_input_ref_element(xml_file, proj_path, inputs_element, railroad, "Railroads")
    add_input_ref_element(xml_file, proj_path, inputs_element, canal, "Canals")

    topo_element = xml_file.add_sub_element(inputs_element, "Topography")
    add_input_ref_element(xml_file, proj_path, topo_element, inDEM, "DEM")
    add_input_ref_element(xml_file, proj_path, topo_element, DrAr, "Flow")

    drain_network_element = xml_file.add_sub_element(inputs_element, "DrainageNetworks")
    network_element = add_input_ref_element(xml_file, proj_path, drain_network_element, seg_network, "Network")
    buffers_element = xml_file.add_sub_element(network_element, "Buffers")
    write_xml_element_with_path(xml_file, buffers_element, "Buffer", "30m Buffer", buf_30m, proj_path)
    write_xml_element_with_path(xml_file, buffers_element, "Buffer", "100m Buffer", buf_100m, proj_path)


def add_drain_area_to_inputs_xml(xml_file, drainage_area, proj_path):
    """
    Adds drainage area data to the input XML
    :param xml_file: The XML file to write to.
    :param drainage_area: The drainage area raster
    :param proj_path: The file path to the project folder.
    :return:
    """
    element = xml_file.find_by_text(find_relative_path(drainage_area, proj_path))

    if element is not None: # if the flow acc is already in the xml file, we don't need to do anything
        return

    inputs_element = xml_file.find("Inputs")

    id = find_next_available_id(xml_file, "DR")
    write_xml_element_with_path(xml_file, inputs_element, "Raster", "Drainage Area", drainage_area, proj_path, xml_id=id)


def find_next_available_id(xml_file, id_base):
    """
    Finds the next ID available in the current XML File
    :param xml_file: The XML file to write to.
    :param id_base: The ID to start with, then count up
    :return: The next available ID
    """
    i = 1
    element = xml_file.find_by_id(id_base + str(i))
    while element is not None:
        i += 1
        element = xml_file.find_by_id(id_base + str(i))
    return id_base + str(i)


def add_input_ref_element(xml_file, proj_path, inputs_element, input_path, new_element_name):
    """
    :param xml_file: The XML file to write to.
    :param proj_path: The file path to the project folder.
    :param inputs_element: The element that holds Input data
    :param input_path: The path to the specific Input data
    :param new_element_name: The ame of the newly added input element.
    :return:
    """
    if input_path is None:
        return
    ref_id = find_element_id_with_path(xml_file, input_path, proj_path)
    if ref_id is not None:
        return xml_file.add_sub_element(inputs_element, new_element_name, tags=[('ref', ref_id)])
    else:
        arcpy.AddMessage(new_element_name + " could not be found in the Inputs XML, and so could not be added to the new Realization in the XML")
        return None


def find_element_id_with_path(xml_file, path, proj_path):
    """
    Returns the ID of the input element that has the relative path given to it
    :param xml_file: The XMLBuilder object
    :param path: The path we want to find
    :param proj_path: Path to the root folder of the project
    :return:
    """
    relative_path = find_relative_path(path, proj_path)
    element = xml_file.find_by_text(relative_path)
    if element is not None:
        parent = xml_file.find_element_parent(element)
        return parent.attrib['id']
    else:
        return None



def validate_inputs(seg_network, road, railroad, canal, is_verbose):
    """
    Checks if the spatial references are correct and that the inputs are what we want
    :param seg_network: The stream network shape file
    :param road: The roads shapefile
    :param railroad: The railroads shape file
    :param canal: The canals shapefile
    :param is_verbose: Tells us if we should print out extra debug messages
    :return:
    """
    if is_verbose:
        arcpy.AddMessage("Validating inputs...")
    try:
        network_sr = arcpy.Describe(seg_network).spatialReference
    except:
        raise Exception("There was a problem finding the spatial reference of the stream network. "
                       + "This is commonly caused by trying to run the Table tool directly after running the project "
                       + "builder. Restarting ArcGIS fixes this problem most of the time.")
    if not network_sr.type == "Projected":
        raise Exception("Input stream network must have a projected coordinate system")

    if road is not None:
        if not arcpy.Describe(road).spatialReference.type == "Projected":
            raise Exception("Input roads must have a projected coordinate system")

    if railroad is not None:
        if not arcpy.Describe(railroad).spatialReference.type == "Projected":
            raise Exception("Input railroads must have a projected coordinate system")

    if canal is not None:
        if not arcpy.Describe(canal).spatialReference.type == "Projected":
            raise Exception("Input canals must have projected coordinate system")

    # --check that input network is shapefile--
    if not seg_network.endswith(".shp"):
        raise Exception("Input network must be a shapefile (.shp)")


def add_mainstem_attribute(out_network):
    """
    Adds the mainstem attribute to our output network
    :param out_network: The network that we want to work with
    :return: None
    """
    list_fields = arcpy.ListFields(out_network,"IsMainCh")
    if len(list_fields) is not 1:
        arcpy.AddField_management(out_network, "IsMainCh", "SHORT", "", "", "", "", "NULLABLE")
    arcpy.CalculateField_management(out_network,"IsMainCh",1,"PYTHON")


def make_layers(out_network, diversion_pts):
    """
    Writes the layers
    :param out_network: The output network, which we want to make into a layer
    :param diversion_pts: The diversion points shapefile
    :return:
    """
    arcpy.AddMessage("Making layers...")
    intermediates_folder = os.path.dirname(out_network)
    buffers_folder = os.path.join(intermediates_folder, "01_Buffers")
    topo_folder = make_folder(intermediates_folder, "02_TopographicMetrics")
    anthropogenic_metrics_folder = make_folder(intermediates_folder, "03_AnthropogenicMetrics")
    perennial_folder = make_folder(intermediates_folder, "04_Perennial")

    trib_code_folder = os.path.dirname(os.path.abspath(__file__))
    symbology_folder = os.path.join(trib_code_folder, 'BRATSymbology')

    dist_to_infrastructure_symbology = os.path.join(symbology_folder, "DistancetoClosestInfrastructure.lyr")
    dist_to_road_in_valley_bottom_symbology = os.path.join(symbology_folder, "DistancetoRoadinValleyBottom.lyr")
    dist_to_road_crossing_symbology = os.path.join(symbology_folder, "DistancetoRoadCrossing.lyr")
    dist_to_road_symbology = os.path.join(symbology_folder, "DistancetoRoad.lyr")
    dist_to_railroad_in_valley_bottom_symbology = os.path.join(symbology_folder, "DistancetoRailroadinValleyBottom.lyr")
    dist_to_railroad_symbology = os.path.join(symbology_folder, "DistancetoRailroad.lyr")
    dist_to_canal_symbology = os.path.join(symbology_folder, "DistancetoCanal.lyr")
    pts_diversion_symbology = os.path.join(symbology_folder, "PointsofDiversion.lyr")
    dist_to_pts_diversion_symbology = os.path.join(symbology_folder, "DistancetoPointsofDiversion.lyr")
    land_use_symbology = os.path.join(symbology_folder, "LandUseIntensity.lyr")
    land_ownership_per_reach_symbology = os.path.join(symbology_folder, "LandOwnershipperReach.lyr")
    priority_translocations_symbology = os.path.join(symbology_folder, "PriorityBeaverTranslocationAreas.lyr")
    slope_symbology = os.path.join(symbology_folder, "ReachSlope.lyr")
    drain_area_symbology = os.path.join(symbology_folder, "UpstreamDrainageArea.lyr")
    buffer_30m_symbology = os.path.join(symbology_folder, "buffer_30m.lyr")
    buffer_100m_symbology = os.path.join(symbology_folder, "buffer_100m.lyr")
    perennial_symbology = os.path.join(symbology_folder, "Perennial.lyr")

    make_buffer_layers(buffers_folder, buffer_30m_symbology, buffer_100m_symbology)
    make_layer(topo_folder, out_network, "Reach Slope", slope_symbology, is_raster=False)
    make_layer(topo_folder, out_network, "Upstream Drainage Area", drain_area_symbology, is_raster=False)

    if diversion_pts is not None:
        try:
            make_layer(os.path.dirname(diversion_pts), diversion_pts, "Provisional Points of Diversion", pts_diversion_symbology, is_raster=False)
        except Exception as err:
            print err
            
    fields = [f.name for f in arcpy.ListFields(out_network)]
    if 'iPC_LU' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Land Use Intensity", land_use_symbology, is_raster=False)
    if 'iPC_RoadX' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Road Crossing", dist_to_road_crossing_symbology, is_raster=False, symbology_field ='iPC_RoadX')
    if 'iPC_Road' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Road", dist_to_road_symbology, is_raster=False, symbology_field ='iPC_Road')
    if 'iPC_RoadVB' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Road in Valley Bottom", dist_to_road_in_valley_bottom_symbology, is_raster=False, symbology_field ='iPC_RoadVB')
    if 'iPC_Rail' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Railroad", dist_to_railroad_symbology, is_raster=False, symbology_field ='iPC_Rail')
    if 'iPC_RailVB' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Railroad in Valley Bottom", dist_to_railroad_in_valley_bottom_symbology, is_raster=False, symbology_field ='iPC_RailVB')
    if 'iPC_Canal' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Canal", dist_to_canal_symbology, is_raster=False, symbology_field ='iPC_Canal')
    if 'iPC_DivPts' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Points of Diversion", dist_to_pts_diversion_symbology, is_raster=False, symbology_field='iPC_DivPts')
    if 'ADMIN_AGEN' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Land Ownership per Reach", land_ownership_per_reach_symbology, is_raster=False, symbology_field='ADMIN_AGEN')
    if 'iPC_Privat' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Priority Beaver Translocation Areas", priority_translocations_symbology, is_raster=False, symbology_field='iPC_Privat')
    if 'oPC_Dist' in fields:
        make_layer(anthropogenic_metrics_folder, out_network, "Distance to Closest Infrastructure", dist_to_infrastructure_symbology, is_raster=False, symbology_field ='oPC_Dist')
    if 'IsPeren' in fields:
        make_layer(perennial_folder, out_network, "Perennial", perennial_symbology, is_raster=False, symbology_field="IsPeren")


def handle_braids(seg_network_copy, canal, proj_path, find_clusters, perennial_network, is_verbose):
    """
    Finds multi-threaded attributes in the network, and optionally finds clusters.
    :param seg_network_copy: The network where data will be updated
    :param canal: The canals shapefile
    :param proj_path: The file path to the project folder.
    :param find_clusters: If true, clusters will be found via the braid handler script
    :param perennial_network: The perennial network shapefile
    :param is_verbose: If true, this option enables ArcMap to provide messages for each step conducted by the tool.
    :return:
    """
    if is_verbose:
        arcpy.AddMessage("Finding multi-threaded attributes...")
    add_mainstem_attribute(seg_network_copy)
    # find braided reaches
    temp_dir = os.path.join(proj_path, 'Temp')
    if not os.path.exists(temp_dir):
        os.mkdir(temp_dir)
    FindBraidedNetwork.main(seg_network_copy, canal, temp_dir, perennial_network, is_verbose)

    if find_clusters:
        arcpy.AddMessage("Finding Clusters...")
        clusters = BRAT_Braid_Handler.find_clusters(seg_network_copy)
        BRAT_Braid_Handler.add_cluster_id(seg_network_copy, clusters)
        # if 'StreamName' is field then run the update_multiCh function
        fields = [f.name for f in arcpy.ListFields(seg_network_copy)]
        if 'StreamName' in fields:
            BRAT_Braid_Handler.update_multi_ch(seg_network_copy)


def make_buffer_layers(buffers_folder, buffer_30m_symbology, buffer_100m_symbology):
    """
    Makes a layer for each buffer
    :param buffers_folder: The path to the buffers folder
    :return: Nothing
    """
    for file_name in os.listdir(buffers_folder):
        if file_name.endswith(".shp"):
            file_path = os.path.join(buffers_folder, file_name)
            given_symbology = None
            if "30m" in file_name:
                new_layer_name = "30 m Buffer"
                given_symbology = buffer_30m_symbology
            elif "100m" in file_name:
                new_layer_name = "100 m Buffer"
                given_symbology = buffer_100m_symbology
            make_layer(buffers_folder, file_path, new_layer_name, given_symbology)


def parse_input_bool(given_input):
    """
    Takes an ArcMap bool input and coverts it to be usable in Python
    :param given_input: The given ArcMap input
    :return: Converted Bool
    """
    if given_input == 'false' or given_input is None:
        return False
    else:
        return True


def delete_with_arcpy(stuffToDelete):
    """
    Deletes everything in a list with arcpy.Delete_management()
    :param stuffToDelete: A list of stuff to delete
    :return:
    """
    for thing in stuffToDelete:
        arcpy.Delete_management(thing)


def run_tests(seg_network_copy, is_verbose):
    """
    Runs tests on the tool's output
    :param seg_network_copy: The network that we want to test
    :return:
    """
    if is_verbose:
        arcpy.AddMessage("Running tests...")
    run_tests = True
    if not run_tests: # don't run tests in execution
        return
    from Tests import test_reach_id_is_unique, report_exceptions, TestException
    test_exceptions = []

    try:
        test_reach_id_is_unique(seg_network_copy)
    except TestException as e:
        test_exceptions.append(str(e))

    report_exceptions(test_exceptions)


if __name__ == '__main__':
    main(
        sys.argv[1],
        sys.argv[2],
        sys.argv[3],
        sys.argv[4],
        sys.argv[5],
        sys.argv[6],
        sys.argv[7],
        sys.argv[8],
        sys.argv[9],
        sys.argv[10],
        sys.argv[11],
        sys.argv[12],
        sys.argv[13],
        sys.argv[14],
        sys.argv[15],
        sys.argv[16],
        sys.argv[17],
        sys.argv[18],
        sys.argv[19])
