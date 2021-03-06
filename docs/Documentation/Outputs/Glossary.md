---
title: BRAT Attribute Table
---
# Naming Limitations using Shapefiles

Because field names in ArcGIS are limited to ten characters, there is a limit to how descriptive those names can be. This page is meant to be a reference for what each field in the stream network produced by BRAT is meant to represent.

## Current pyBRAT Values
These are values that are presently generated and used by the latest version of pyBRAT (3.0.20 at the time of writing). They are sorted by what stage they are created in, not alphabetically.

**FID -** This attribute is automatically assigned to every segment in a stream network. Each segment should have a unique FID value.

- Field Type: "FID"
- Generation Method: Automatic

**Shape -** The type of vector that this element is. This attribute is automatically generated. In a stream network, this value should be *Polyline*.
- Field Type: "Geometry"
- Generation Method: Automatic

**ReachID -** This attribute is generated based on the FID. By creating our own attribute, we give ourselves more flexibility in how we capture data values. For a technician running BRAT, it is effectively identical to FID. 
- Field Type: "Long"
- Generation Method: SegmentNetwork.py script or the BRAT Table tool

**ReachLen -** The length of the polyline. 
- Field Type: "Double"
- Generation Method: SegmentNetwork.py script

**StreamName -** The name of the stream (for example, "Grouse Creek" or "Snake River"). Some datasets come with this value automatically. 
- Field Type: "String"
- Generation Method: Pre-existing in some datasets

**StreamID -** Generated based on the StreamName when running SegmentNetwork.py or AddAttributes.py. Every reach with the same StreamName value is given the same StreamID value, counting up from 1. Used primarily in the Drainage Area Check tool.
- Field Type: "Long"
- Generation Method: SegmentNetwork.py script

**StreamLen -** The length the streams, identified using StreamID. 
- Field Type: "Double"
- Generation Method: SegmentNetwork.py script

**ReachDist -** How far a reach is from the headwaters of the stream. Calculated based off of StreamID.
- Field Type: "Double"
- Generation Method: SegmentNetwork.py script

**iGeo_ElMax -** The maximum elevation found within a buffer around the reach. Used in calculating slope. Extracted from the DEM given.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iGeo_ElMin -** The minimum elevation found within a buffer around the reach. Used in calculating slope. Extracted from the DEM given.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iGeo_Len -** The length of the reach. Redundant with ReachLen, but removal is currently low priority.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iGeo_Slope -** The average slope of the reach. Calculated using iGeo_ElMax, iGeo_ElMin, and iGeo_Len.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iGeo_DA -** The maximum drainage area value found in a buffer around the stream. Extracted from the drainage area raster given, or from a DA raster derived from the DEM (if no DA raster was given).
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iVeg_100EX -** The average VEG_CODE value on the existing vegetation raster within a 100m buffer of the reach.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iVeg_30EX -** The average VEG_CODE value on the existing vegetation raster within a 30m buffer of the reach.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iVeg_100Hpe -** The average VEG_CODE value on the historic vegetation raster within a 100m buffer of the reach.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iVeg_30Hpe -** The average VEG_CODE value on the historic vegetation raster within a 30m buffer of the reach.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_RoadX -** The distance of the reach to the nearest point where a road crosses the stream.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_Road -** The distance of the reach to the closest road.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_RoadVB -** The distance of the reach to the closest road in the valley bottom.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_Rail -** The distance of the reach to the closest railroad.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_RailVB -** The distance of the reach to the closest road in the valley bottom.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**oPC_Dist -** The smallest value found in "iPC_RoadX", "iPC_Road", "iPC_RoadVB", "iPC_Rail", and "iPC_RailVB". 
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_LU -** The average land use value in a 100m buffer around the reach.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_VLowLU -** The percentage of cells in the buffer classified as having a low land use value.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_LowLU -** The percentage of cells in the buffer classified as having a low land use value.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_ModLU -** The percentage of cells in the buffer classified as having a low land use value.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**iPC_HighLU -** The percentage of cells in the buffer classified as having a low land use value.
- Field Type: "Double"
- Generation Method: BRAT Table Tool

**IsPeren-** An integer value. If the reach is part of the perennial network, the value will be 1. Otherwise, it will be 0.

**IsMultiCh -** An integer value. If the reach is part of a multi-branch system, the value will be 1. Otherwise, it will be 0.

- Field Type: "Long"
- Generation Method: BRAT Table Tool

**IsMainCh -** An integer value. If the reach is the primary branch of a multi-branch system, the value will be 1. Otherwise, it will be 0. Defaults to a value of 1 for non-multibranch reaches, a value of 0 for multi-branch reaches. Must be manually edited to indicate main channels in order to properly use the optional Braid Handler tool.
- Field Type: "Long"
- Generation Method: BRAT Table Tool

**ClusterID -** If the reach is not part of a multi-branch system, this wil have a value of -1. Otherwise, every reach in a cluster of multi-branch reaches will share a ClusterID value. This value will be used for fixing multi-branch drainage area values in the optional Braid Handler tool. If the technician wants to, they can manually edit these values.
- Field Type: "Long"
- Generation Method: BRAT Table Tool or the Braid Handler tool

**iHyd_QLow -** The value for low stream flow (CFS) in the reach.

- Field Type: "Double"
- Generation Method: iHyd tool

**iHyd_Q2 -** The value for high stream flow (CFS) in the reach.

- Field Type: "Double"
- Generation Method: iHyd tool

**iHyd_SPLow-** The stream power in watts of the reach for the low stream flow.

- Field Type: "Double"
- Generation Method: iHyd tool

**iHyd_SP2-** The stream power in watts of the reach for the high stream flow.

- Field Type: "Double"
- Generation Method: iHyd tool

**oVC_HPE-** Output of beaver dam density based on historic vegetation based on the FIS classifications that the user input for the "VEG_CODE" field in the historic vegetation raster.

- Field Type: "Double"
- Generation Method: Vegetation Dam Capacity Model tool

**oVC_EX-** Output of beaver dam density based on existing vegetation based on the FIS classifications that the user input for the "VEG_CODE" field in the existing vegetation raster.

- Field Type: "Double"
- Generation Method: Vegetation Dam Capacity Model tool

**oCC_HPE-**  Final capacity output of historic beaver dam dam density based on the combined inputs of the reach.

- Field Type: "Double"
- Generation Method: Combined Dam Capacity tool

**mCC_HPE_CT-** Final capacity output of historic beaver dam dam count based on the combined inputs of the reach.

- Field Type: "Long"
- Generation Method: Combined Dam Capacity tool

**oCC_EX-** Final capacity output of existing beaver dam dam density based on the combined inputs of the 

- Field Type: "Double"
- Generation Method: Combined Dam Capacity tool

**mCC_EX_CT-** Final capacity output of existing beaver dam dam count based on the combined inputs of the reach.

- Field Type: "Long"
- Generation Method: Combined Dam Capacity tool

**mCC_HisDep-**  The departure between the Historic dam count ("mCC_HPE_CT") and the Existing dam count  ("mCC_EX_CT")

- Field Type: "Long"
- Generation Method: Combined Dam Capacity tool

**oPBRC_UI-**  Management output that outlines the unsuitable or limited beaver dam opportunities. Identifies the limiting factor that is limiting the reach from optimal beaver dam construction.

- Field Type: "String"
- Generation Method: Constraints and Opportunities tool

**oPBRC_UD-**  Management output that outlines areas beavers can build dams, but proximity to anthropogenic infrastructure or high land use intensity could pose a threat to long-term persistence and tolerance of beaver dams.

- Field Type: "String"
- Generation Method: Constraints and Opportunities tool

**oPBRC_CR-** Dam-building beaver restoration opportunities with categories describe levels of effort required for establishing beaver dams on the landscape. This is subset into those reaches that are defined as a "oPBC_UI" score of "Negligible Risk" and "Minor Risk" in order to further aid in possible reaches for management to focus their efforts on in order to get the most bang for their buck.

- Field Type: "String"
- Generation Method: Constraints and Opportunities tool

**ConsAreas-** Binary "yes" or "no" designating whether a reach occurs within a conservation or protected area.

* Field Type: "String"
* Generation Method: Constraints and Opportunities tool

**ConsEase-** Binary "yes" or "no" designating whether a reach occurs within a conservation easement.

- Field Type: "String"
- Generation Method: Constraints and Opportunities tool

**ObsDams-** Binary "yes" or "no" designating whether surveyed dams occurred along a reach. Dams within 60 meters of the NHD are snapped to the network for this field.

- Field Type: "String"
- Generation Method: Constraints and Opportunities tool

**DamStrat-** Management strategies to promote dam building based primarily on locations of surveyed dams, conservation/protected areas and conservation easements, and existing dam building capacity. 

* Field Type: "String"
* Generation Method: Constraints and Opportunities tool

**e_DamCT-** Number of surveyed beaver dams snapped to a reach.

- Field Type: "Double"
- Generation Method: Data Capture Validation tool

**e_DamDens-** Density of surveyed beaver dams ("e_DamCT"/"iGeo_Len").

- Field Type: "Double"
- "Generation Method: Data Capture Validation tool

**e_DamPcC-** Percent of predicted existing capacity occupied by surveyed dams ("e_DamDens"/"oCC_EX").

- Field Type: "Double"
- Generation Method: Data Capture Validation tool

**ConsVRest-** Current beaver dam management strategies based on intrinsic restoration/conservation opportunities and surveyed beaver dam capacity. Reaches with at least 25% of predicted capacity already occupied by dams are classified as "Immediate - Beaver Conservation" areas whereas those with less than 25% of capacity occupied are classified as "Immediate - Beaver Translocation".

- Field Type: "String"
- Generation Method: Data Capture Validation tool

**BRATvSurv-** Predicted existing capacity vs. surveyed dam capacity ("mCC_EX_CT"/"e_DamCt"). Reaches with no surveyed dams are assigned a value of -1.

- Field Type: "Float"
- Generation Method: Data Capture Validation tool

**ExCategor-** Categorization of existing dam building capacity, inclding Pervasive (>15 - 40 dams/km), Frequent (>5 - 15 dams/km), Occasional (>1 - 5 dams/km), Rare (>0 - 1 dams/km) and None (0 dams/km).

- Field Type: "String"
- Generation Method: Data Capture Validation tool

**HpeCategor-** Categorization of historic dam building capacity, inclding Pervasive (>15 - 40 dams/km), Frequent (>5 - 15 dams/km), Occasional (>1 - 5 dams/km), Rare (>0 - 1 dams/km) and None (0 dams/km).

- Field Type: "String"
- Generation Method: Data Capture Validation tool

**mCC_EXvHPE-** Proportion of historic capacity remaining ("oCC_EX"/"oCC_HPE").

- Field Type: "Float"
- Generation Method: Data Capture Validation tool

## Depreciated pyBRAT Values
These are values that were once used by pyBRAT, but were discontinued for one reason or another.

**SegID-** Was renamed to ReachID. Served the same purpose.

**SegLength-** Was renamed to ReachLen. Served the same purpose.

**IsBraided-** Was renamed to "IsMultiCh" for accuracy reasons. Served the same purpose.

**IsMainstem-** Was renamed to "IsMainCh" for clarity reasons. Served the same purpose.















