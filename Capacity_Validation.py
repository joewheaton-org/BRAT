# -------------------------------------------------------------------------------
# Name:        BRAT Validation
# Purpose:     Tests the output of BRAT against a shape file of beaver dams
#
# Author:      Braden Anderson
#
# Created:     05/2018
# -------------------------------------------------------------------------------

from SupportingFunctions import write_xml_element_with_path, find_relative_path, find_folder, \
    make_folder, find_available_num_suffix, find_available_num_prefix, make_layer
import os
import arcpy
# import matplotlib as mpl # for plot code
# mpl.use('Agg')
# import matplotlib.pyplot as plt
import scipy.stats as stat
import numpy as np
# import glob
import XMLBuilder
reload(XMLBuilder)
XMLBuilder = XMLBuilder.XMLBuilder


def main(in_network, output_name, dams=None, da_threshold=None):
    """
    The main function
    :param in_network: The output of BRAT (a polyline shapefile)
    :param dams: A shapefile containing a point for each dam
    :param output_name: The name of the output shape file
    :param da_threshold: Drainage area at which stream is presumably too large for dam building
    :return:
    """


    if da_threshold == "None":
        da_threshold = None

    arcpy.env.overwriteOutput = True
    arcpy.env.workspace = 'in_memory'

    proj_path = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(in_network))))
    if dams:
        dams = copy_dams_to_inputs(proj_path, dams, in_network)



    if output_name.endswith('.shp'):
        output_network = os.path.join(os.path.dirname(in_network), output_name)
    else:
        output_network = os.path.join(os.path.dirname(in_network), output_name + ".shp")
    arcpy.Delete_management(output_network)

    # add catch for old terminology
    fields = [f.name for f in arcpy.ListFields(in_network)]
    if 'oCC_PT' in fields:
        occ_hpe = 'oCC_PT'
    else:
        occ_hpe = 'oCC_HPE'
        
    # remove Join_Count if already present in conservation restoration output
    if 'Join_Count' in fields:
        arcpy.DeleteField_management(in_network, 'Join_Count')
        
    dam_fields = ['e_DamCt', 'e_DamDens', 'e_DamPcC', 'ConsVRest', 'BRATvSurv']
    other_fields = ['ExCategor', 'HpeCategor', 'mCC_EXvHPE']
    new_fields = dam_fields + other_fields

    input_fields = ['SHAPE@LENGTH', 'oCC_EX', occ_hpe, 'iGeo_DA', 'oPBRC_CR', 'mCC_EX_CT']

    if dams:
        arcpy.AddMessage("Adding fields that need dam input...")
        set_dam_attributes(in_network, output_network, dams,
                           dam_fields + ['Join_Count'] + input_fields, new_fields, da_threshold)
    else:
        arcpy.CopyFeatures_management(in_network, output_network)
        add_fields(output_network, other_fields)

    arcpy.AddMessage("Adding fields that don't need dam input...")
    set_other_attributes(output_network, other_fields + input_fields)

    if dams:
        clean_up_fields(in_network, output_network, new_fields)

    # Makes observed vs. predicted plot. Use the R code on master branch instead.
    # if dams:
    #    plot_name = observed_v_predicted_plot(output_network)

    # electivity table output moved to collect_summary_products tool
    # if dams:
    #    make_electivity_table(output_network, output_name)

    write_xml(proj_path, in_network, output_network, None)

    make_layers(output_network, dams)


def copy_dams_to_inputs(proj_path, dams, in_network):
    """
    If the given dams are not in the inputs,
    :param proj_path: The path to the project root
    :param dams: The path to the given dams
    :param in_network: the input Conservation Restoration Network
    :return: Filepath to dams in inputs folder
    """
    if proj_path in dams:
        # The dams input is already in our project folder, so we don't need to copy it over
        return dams

    inputs_folder = find_folder(proj_path, "Inputs")
    beaver_dams_folder = find_folder(inputs_folder, "*[0-9]*_BeaverDams")
    if beaver_dams_folder is None:
        beaver_dams_folder = make_folder(inputs_folder, find_available_num_prefix(inputs_folder) + "_BeaverDams")
    new_dam_folder = make_folder(beaver_dams_folder, "Beaver_Dam_" + find_available_num_suffix(beaver_dams_folder))
    new_dam_path = os.path.join(new_dam_folder, os.path.basename(dams))
    coord_sys = arcpy.Describe(in_network).spatialReference

    arcpy.Project_management(dams, new_dam_path, coord_sys)

    return new_dam_path


def set_dam_attributes(brat_output, output_path, dams, req_fields, new_fields, da_threshold):
    """
    Sets all the dam info and updates the output file with that data
    :param brat_output: The polyline we're basing everything on
    :param output_path: The polyline shapefile with BRAT output
    :param dams: The points shapefile of observed dams
    :param req_fields: The fields needed to calculate new fields
    :param new_fields: Fields to add to the network
    :param da_threshold:
    :return: Drainage area at which stream is presumably too large for dam building
    """
    # snap dams within 5 meters to network if above DA threshold, otherwise snap dams within 60 meters
    if da_threshold:
        temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(brat_output)))), 'Temp')
        tmp_above_threshold = arcpy.MakeFeatureLayer_management(brat_output, 'tmp_above_threshold')
        above_threshold_shp = os.path.join(temp_dir, 'tmp_above_da_threshold.shp')
        tmp_below_threshold = arcpy.MakeFeatureLayer_management(brat_output, 'tmp_below_threshold')
        below_threshold_shp = os.path.join(temp_dir, 'tmp_below_da_threshold.shp')
        quer_above = """"{}" >= {}""".format('iGeo_DA', 65)
        quer_below = """"{}" < {}""".format('iGeo_DA', 65)
        arcpy.SelectLayerByAttribute_management(tmp_above_threshold, 'NEW_SELECTION', quer_above)
        arcpy.CopyFeatures_management(tmp_above_threshold, above_threshold_shp)
        arcpy.SelectLayerByAttribute_management(tmp_below_threshold, 'NEW_SELECTION', quer_below)
        arcpy.CopyFeatures_management(tmp_below_threshold, below_threshold_shp)
        arcpy.Snap_edit(dams, [[above_threshold_shp, 'EDGE', '5 Meters']])
        arcpy.Snap_edit(dams, [[below_threshold_shp, 'EDGE', '60 Meters']])
    # snap all dams within 60 meters to network if no DA threshold provided
    else:
        arcpy.Snap_edit(dams, [[brat_output, 'EDGE', '60 Meters']])
    # should select all dams snapped to network
    arcpy.SpatialJoin_analysis(brat_output, dams, output_path,
                               join_operation='JOIN_ONE_TO_ONE', join_type='KEEP_ALL', match_option='INTERSECT')

    # add new fields to network
    add_fields(output_path, new_fields)

    # calculate new field values
    with arcpy.da.UpdateCursor(output_path, req_fields) as cursor:
        for row in cursor:
            dam_num = row[-7]        # seventh to last attribute
            seg_length = row[-6]   # sixth to last attribute
            if seg_length is None:
                seg_length = 0
            occ_ex = row[-5]        # fifth to last attribute
            # TODO Is it necessary to initialize these values?
            occ_hpe = row[-4]        # fourth to last attribute
            igeo_da = row[-3]       # third to last attribute
            cons_field = row[-2]     # second to last attribute
            mcc_ex_ct = row[-1]     # last attribute

            # eDam_Ct: set equal to join count from snapped dams
            row[0] = dam_num
            row[1] = dam_num / seg_length * 1000  # calculate surveyed dam density

            # BRATvSurv: calculate predicted (BRAT) capacity count vs. observed (surveyed) dam count
            if row[0] == 0:
                row[4] = -1
            else:
                row[4] = mcc_ex_ct / row[0]

            # e_DamPcC: calculate proportion of predicted capacity occupied by dams
            if occ_ex == 0:
                row[2] = 0
            else:
                row[2] = row[1] / row[-5]

            # ConsVRest: differentiate management strategies based on dam occupancy
            if row[-2] == "Easiest - Low-Hanging Fruit":
                if row[2] >= 0.25:
                    row[3] = "Immediate: Beaver Conservation"
                else:
                    row[3] = "Immediate: Potential Beaver Translocation"
            elif row[-2] == "Straight Forward - Quick Return":
                row[3] = "Mid Term: Process-based Riparian Vegetation Restoration"
            elif row[-1] == "Strategic - Long-Term Investment":
                row[3] = "Long Term: Riparian Vegetation Reestablishment"
            else:
                row[3] = "Low Capacity Habitat"

            cursor.updateRow(row)

    arcpy.DeleteField_management(output_path, ["Join_Count", "TARGET_FID"])

    add_snapped_attribute(dams, brat_output)


def add_snapped_attribute(dams, brat_output):
    """ Adds attribute to dams indicating whether point was snapped to network, and therefore used in the validation
    : param dams: Shapefile of dams used in validation
    : param brat_output: Path to network with BRAT results
    : return:
    """
    out_dams = os.path.join(os.path.dirname(dams), 'Dams_Snapped.shp')
    arcpy.SpatialJoin_analysis(dams, brat_output, out_dams,
                               join_operation='JOIN_ONE_TO_ONE', join_type='KEEP_ALL', match_option='INTERSECT')
    arcpy.AddField_management(out_dams, 'Snapped', 'TEXT')
    with arcpy.da.UpdateCursor(out_dams, ['Join_Count', 'Snapped']) as cursor:
        for row in cursor:
            if row[0] > 0:
                row[1] = 'Snapped to network'
            else:
                row[1] = 'Not snapped to network'
            cursor.updateRow(row)
    # clean up dam fields
    dam_fields = [f.name for f in arcpy.ListFields(dams)]
    dam_fields.append('Snapped')
    out_fields = [f.name for f in arcpy.ListFields(out_dams)]
    for field in out_fields:
        if field not in dam_fields:
            arcpy.DeleteField_management(out_dams, field)
    # only keep edited dam shapefile and rename as original filename
    arcpy.Delete_management(dams)
    arcpy.Rename_management(out_dams, dams)


def add_fields(output_path, new_fields):
    """
    Adds the fields we want to our output shape file
    :param output_path: Our output shape file
    :param new_fields: All the fields we want to add
    :return:
    """
    text_fields = ['ExCategor', 'HpeCategor', 'ConsVRest']
    for field in new_fields:
        if field in text_fields:
            arcpy.AddField_management(output_path, field, field_type="TEXT", field_length=50)
        else:  # we assume that the default is doubles
            arcpy.AddField_management(output_path, field, field_type="DOUBLE", field_precision=0, field_scale=0)


def set_other_attributes(output_path, fields):
    """
    Sets the attributes of all other things we want to do
    :param output_path: The polyline shapefile with BRAT output
    :param fields: The fields we want to update
    :return:
    """
    with arcpy.da.UpdateCursor(output_path, fields) as cursor:
        for row in cursor:
            # TODO Does this need to be initialized?
            seg_length = row[-6]  # sixth to last attribute
            if seg_length is None:
                seg_length = 0
            occ_ex = row[-5]  # fifth to last attribute
            occ_hpe = row[-4]  # fourth to last attribute

            # Handles Ex_Categor
            row[0] = handle_category(occ_ex)

            # Handles Hpe_Categor
            row[1] = handle_category(occ_hpe)

            # Handles mCC_EXtoHPE
            if occ_hpe != 0:
                row[2] = occ_ex / occ_hpe
            else:
                row[2] = 0

            cursor.updateRow(row)


def handle_category(occ_variable):
    """
    Returns a string based on the oCC value given to it
    :param occ_variable: The oCC variable that needs to be parsed
    :return: oCC category string
    """
    if occ_variable == 0:
        return "None"
    elif 0 < occ_variable <= 1:
        return "Rare"
    elif 1 < occ_variable <= 5:
        return "Occasional"
    elif 5 < occ_variable <= 15:
        return "Frequent"
    elif 15 < occ_variable <= 40:
        return "Pervasive"
    else:
        return "UNDEFINED"


def clean_up_fields(brat_network, out_network, new_fields):
    """
    Removes unnecessary fields
    :param brat_network: The original, unmodified stream network
    :param out_network: The output network
    :param new_fields: All the fields we added
    :return:
    """
    original_fields = [field.baseName for field in arcpy.ListFields(brat_network)]
    desired_fields = original_fields + new_fields
    output_fields = [field.baseName for field in arcpy.ListFields(out_network)]

    remove_fields = []
    for field in output_fields:
        if field not in desired_fields:
            remove_fields.append(field)

    if len(remove_fields) > 0:
        arcpy.DeleteField_management(out_network, remove_fields)


def make_layers(output_network, dams):
    """
    Makes the layers for the modified output
    :param output_network: The path to the network that we'll make a layer from
    :param dams: Filepath to dams in the project folder
    :return:
    """
    arcpy.AddMessage("Making layers...")
    analysis_folder = os.path.dirname(output_network)
    validation_folder_name = find_available_num_prefix(analysis_folder) + "_Validation"
    validation_folder = make_folder(analysis_folder, validation_folder_name)

    trib_code_folder = os.path.dirname(os.path.abspath(__file__))
    symbology_folder = os.path.join(trib_code_folder, 'BRATSymbology')

    dam_symbology = os.path.join(symbology_folder, "SurveyedBeaverDamLocations.lyr")
    historic_remaining_symbology = os.path.join(symbology_folder, "PercentofHistoricDamCapacityRemaining.lyr")
    pred_v_surv_symbology = os.path.join(symbology_folder, "PredictedDamCountvs.SurveyedDamCount.lyr")
    management_strategies_symbology = os.path.join(symbology_folder, "CurrentBeaverDamManagementStrategies.lyr")
    occupancy_symbology = os.path.join(symbology_folder, "PercentofExistingCapacityOccupiedbySurveyedDams.lyr")

    make_layer(validation_folder, output_network, "Percent of Historic Dam Capacity Remaining",
               historic_remaining_symbology, is_raster=False, symbology_field="mCC_EXvHPE")

    if dams is not None:
        make_layer(os.path.dirname(dams), dams, "Surveyed Beaver Dam Locations",
                   dam_symbology, is_raster=False, symbology_field="Snapped")
        make_layer(validation_folder, output_network, "Predicted Dam Count vs. Surveyed Dam Count",
                   pred_v_surv_symbology, is_raster=False, symbology_field="BRATvSurv")
        make_layer(validation_folder, output_network, "Current Beaver Dam Management Strategies",
                   management_strategies_symbology, is_raster=False, symbology_field="ConsVRest")
        make_layer(validation_folder, output_network, "Occupancy Rate of Surveyed Beaver Dams",
                   occupancy_symbology, is_raster=False, symbology_field="e_DamPcC")

        
def make_electivity_table(output_network):
    """
    Makes table with totals and electivity indices for modeled capacity categories
    (i.e., none, rare, occasional, frequent, pervasive)
    :param output_network: The stream network output by the BRAT model with fields added from capacity tools
    :return:
    """
    # convert network data to numpy table
    brat_table = arcpy.da.TableToNumPyArray(output_network,
                                            ['iGeo_Len', 'e_DamCt', 'mCC_EX_CT', 'e_DamDens', 'oCC_EX', 'ExCategor'],
                                            skip_nulls=True)
    tot_length = brat_table['iGeo_Len'].sum()
    tot_surv_dams = brat_table['e_DamCt'].sum()
    tot_brat_cc = brat_table['mCC_EX_CT'].sum()
    avg_surv_dens = tot_surv_dams/(tot_length/1000)
    avg_brat_dens = tot_brat_cc/(tot_length/1000)
    electivity_table = ['', 'm', 'km', '%', '# of dams', '# of dams', 'dams/km', 'dams/km', '%', '']
    add_electivity_category(brat_table, 'None', electivity_table, tot_length, tot_surv_dams)
    add_electivity_category(brat_table, 'Rare', electivity_table, tot_length, tot_surv_dams)
    add_electivity_category(brat_table, 'Occasional', electivity_table, tot_length, tot_surv_dams)
    add_electivity_category(brat_table, 'Frequent', electivity_table, tot_length, tot_surv_dams)
    add_electivity_category(brat_table, 'Pervasive', electivity_table, tot_length, tot_surv_dams)
    electivity_table.append(['Total', tot_length, tot_length/1000, 'NA', tot_surv_dams, tot_brat_cc,
                             avg_surv_dens, avg_brat_dens, tot_surv_dams/tot_brat_cc, 'NA'])

    # set up proper folder structure and save CSV there
    project_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(output_network))))
    summary_folder = make_folder(project_folder, "Summary_Products")
    tables_folder = make_folder(summary_folder, "SummaryTables")
    out_csv = os.path.join(tables_folder, 'Electivity_Index.csv')
    np.savetxt(out_csv, electivity_table, fmt='%s', delimiter=',',
               header="Segment Type, Stream Length, Stream Length,"
                      " % of Drainage Network, Surveyed Dams, BRAT Estimated Capacity,"
                      " Average Surveyed Dam Density, Average BRAT Predicted Density,"
                      " % of Modeled Capacity, Electivity Index")


def add_electivity_category(brat_table, category, output_table, tot_length, tot_surv_dams):
    """
    Calculates values for each modeled capacity category and adds to output table
    :param brat_table: The current BRAT Table
    :param category: The oCC category to add
    :param output_table: The table to output data to
    :param tot_length: The total length of the network
    :param tot_surv_dams: The total number of surveyed dams in the network
    :return:
    """
    cat_tbl = brat_table[brat_table['ExCategor'] == category]
    length = cat_tbl['iGeo_Len'].sum()
    length_km = length/1000
    network_prop = 100*cat_tbl['iGeo_Len'].sum()/tot_length
    surv_dams = cat_tbl['e_DamCt'].sum()
    brat_cc = cat_tbl['mCC_EX_CT'].sum()
    surv_dens = surv_dams/length_km
    brat_dens = brat_cc/length_km
    prop_mod_cap = 100*surv_dams/(brat_cc+0.000001)
    electivity = (surv_dams/tot_surv_dams)/(network_prop/100)
    output_table.append([category, length, length_km, network_prop, surv_dams,
                         brat_cc, surv_dens, brat_dens, prop_mod_cap, electivity])


def observed_v_predicted_plot(output_network):
    """
    Creates plot comparing observed vs predicted. [This is currently unused]
    :param output_network: The Data Validation Network that was created
    :return: The filepath to the plot
    """
    x, y = clean_values(output_network)
    # set up plot
    fig = plt.figure()
    fig.add_axes()
    ax = fig.add_subplot(111)
    ax.set(title='Predicted vs. Observed Dam Counts (per reach)',
           xlabel='Predicted Number of Dams',
           ylabel='Observed Number of Dams')
    # set axis range
    if max(x) > max(y):
        ax.set_xlim(0, round(max(x)+2), 1)
        ax.set_ylim(0, round(max(x)+2), 1)
    else:
        ax.set_xlim(0, round(max(y)+2), 1)
        ax.set_ylim(0, round(max(y)+2), 1)
    # plot data points, regression line, 1:1 reference
    plot_points(x, y, ax)
    if len(x) > 1:
        plot_regression(x, y, ax)
    else:
        print "No regression line plotted - only one reach with dams observed"
    ax.plot([0, 10], [0, 10], color='blue', linewidth=1.5, linestyle=":", label='Line of Perfect Agreement')
    # add legend
    legend = plt.legend(loc="upper left", bbox_to_anchor=(1,1))
    # save plot
    project_folder = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(output_network))))
    summary_folder = make_folder(project_folder, "Summary_Products")
    tables_folder = make_folder(summary_folder, "SummaryTables")
    plot_name = os.path.join(tables_folder, "Predicted_vs_Expected_Plot.png")
    plt.savefig(plot_name, bbox_extra_artists=(legend,), bbox_inches='tight')
    return plot_name


def clean_values(output_network):
    """
    Removes unwanted values from the stream network
    :param output_network: The Data Validation Network that was created
    :return: Values for x and y
    """
    # pull e_DamCt (observed) and oCC_EX (predicted) from output network
    mcc_ex_ct = arcpy.da.FeatureClassToNumPyArray(output_network, ['mCC_EX_CT']).astype(np.float)
    e_dam_ct = arcpy.da.FeatureClassToNumPyArray(output_network, ['e_DamCt']).astype(np.float)
    # pull out none values
    x = mcc_ex_ct[np.isnan(e_dam_ct) is False]
    y = e_dam_ct[np.isnan(e_dam_ct) is False]
    # pull out observed values of zero
    x1 = x[np.equal(y, 0) is False]
    y1 = y[np.equal(y, 0) is False]
    return x1, y1


def plot_points(x, y, axis):
    """
    Plots points based on their x and y values
    :param x: X values for points
    :param y: Y values for points
    :param axis: Axis for current graph
    :return:
    """
    # generate some random jitter between 0 and 1
    if len(x) > 0 and x.std() != 0:
        jitter = (np.random.rand(*x.shape)-0.5)/x.std()
    else:
        jitter = (np.random.rand(*x.shape)-0.5)/10
    # plot points with predicted dams < observed dams in red
    red_x = x[np.greater(y, x) is True]
    red_y = y[np.greater(y, x) is True]
    jitter_red = jitter[np.greater(y, x) is True]
    jitter_red_x = np.add(red_x, jitter_red)
    jitter_red_y = np.add(red_y, jitter_red)
    axis.scatter(jitter_red_x, jitter_red_y, color="red", label="BRAT Underestimate")
    # plot points with expected dams >= observed dams in blue
    blue_x = x[np.greater_equal(x, y) is True]
    blue_y = y[np.greater_equal(x, y) is True]
    jitter_blue = jitter[np.greater_equal(x, y) is True]
    jitter_blue_x = np.add(blue_x, jitter_blue)
    jitter_blue_y = np.add(blue_y, jitter_blue)
    axis.scatter(jitter_blue_x, jitter_blue_y, color="blue", label="BRAT Accurate")


def plot_regression(x, y, axis):
    """
    Plots regression points based on their x and y values
    :param x: X values for points
    :param y: Y values for points
    :param axis: Axis for current graph
    :return:
    """
    # calculate regression equation of e_DamCt ~ mCC_EX_CT and assign to variable
    regression = stat.linregress(x, y)
    model_x = np.arange(0.0, round(max(x))+2, 0.1)
    model_y = regression.slope * model_x + regression.intercept
    # plot regression line
    axis.plot(model_x, model_y,  color='black', linewidth=2.0, linestyle='-', label='Regression line')
    # calculate prediction intervals and plot as shaded areas
    n = len(x)
    error = stat.t.ppf(1-0.025, n-2) * regression.stderr
    upper_ci = model_y + error
    lower_ci = model_y - error
    axis.fill_between(model_x, y1=upper_ci, y2=lower_ci, facecolor='red', alpha=0.3, label="95% Confidence Interval")
    # in-plot legend
    axis.legend(loc='best', frameon=False)


def write_xml(proj_path, in_network, out_network, plot_name):
    """
    Writes relevant data into the XML
    :param proj_path:  The file path to the BRAT project folder
    :param in_network: The input Conservation Restoration network
    :param out_network: The newly created Data Validation network
    :param plot_name: The file path to the created plot
    :return:
    """
    xml_file_path = os.path.join(proj_path, "project.rs.xml")

    if not os.path.exists(xml_file_path):
        arcpy.AddWarning("XML file not found. Could not update XML file")
        return

    xml_file = XMLBuilder(xml_file_path)
    in_network_rel_path = find_relative_path(in_network, proj_path)

    path_element = xml_file.find_by_text(in_network_rel_path)
    analysis_element = xml_file.find_element_parent(xml_file.find_element_parent(path_element))

    write_xml_element_with_path(xml_file, analysis_element, "Vector", "BRAT Data Validation", out_network, proj_path)
    # write_xml_element_with_path(xml_file, analysis_element, "Plot", "Obsrved vs Predicted Plot", plot_name, proj_path)

    xml_file.write()


if __name__ == "__main__":
    main(sys.argv[1],
         sys.argv[2],
         sys.argv[3],
         sys.argv[4])
