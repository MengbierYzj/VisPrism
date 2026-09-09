# Gitlab

Source: https://design.gitlab.com/data-visualization/overview
Excel row: 13
Converted: 2026-07-30T23:11:34
Status: converted from static HTML

## Visualization Guide Content

Overview

Data visualization is part of the

design system extended layer

🤝

owned by

group

optimize

.

Questions or feedback? Reach out to

#data-exploration-dashboards on slack

.

Data visualizations pull insights from data sets into a narrative and allow users to explore data themselves to discover their own insights.

Usage

Data visualizations should be:

Cohesive

Structured

Readable

Understandable

When creating a data visualization, keep in mind:

In terms of cognition, visualizations where points are positioned along a common scale are most easily understood.

We are generally less adept at understanding lengths without a common base.

We are often worst at perceiving angles, directions and areas (which is why pie charts, for example, are generally not a great way to present data).

Types

There are six main categories of data visualizations:

Hierarchical: shows portions of a whole (ex. treemaps, node, and sunburst diagrams).

Relational: shows the flow of assets (ex. network diagrams, matrices, and sankey diagrams).

Spatial: shows data that can be mapped (ex. location map)

Temporal: shows changes in data over time (ex. timeline)

Spatial-temporal: shows data that can be mapped over time (ex. heat map)

Statistical graphics: shows the composition of data (ex. column charts, area charts, and line charts)

We have use cases for Relational, Statistical, and Spatial-temporal. The other categories will be built when there is an appropriate use case.

Relational

The GitLab

commit graph

is an example of a relational data visualization, as it shows how all of the individual commits are related to the master.

TODO:

Create component for the Commit Graph in GitLab UI

Create an issue

Spatial-temporal

A heat map is an example of a spatial-temporal data visualization.

Heat maps can be used to more quickly visualize and compare values in a dataset. In heat maps, data points are grouped and displayed using shades of color. Darker colors are generally used to communicate a higher density of data.

<script>

export default {

data() {

return {

chartData: [

[0, 5, 5],

[5, 2, 1],

[2, 3, '-'],

[3, 5, 4],

[4, 0, 10],

[5, 0, 4],

[6, 0, 6],

],

xAxisLabels: ['12', '1', '2', '3', '4', '5', '6', '7', '8', '9', '10', '11'],

yAxisLabels: ['Sat', 'Fri', 'Thu', 'Wed', 'Tue', 'Mon', 'Sun'],

};

},

};

</script>

<template>

<div style="height: 400px">

<gl-heatmap

:data-series="chartData"

:x-axis-labels="xAxisLabels"

:y-axis-labels="yAxisLabels"

x-axis-name="Hour"

y-axis-name="Day"

:show-tooltip="true"

/>

</div>

</template>

Statistical graphics

Charts are statistical graphics that help users quickly digest, visualize and see trends in their data.

Full list of chart types and design specifications is detailed on the

Charts

component page.

<script>

export default {

data() {

return {

bars: [

{ name: 'Fun 1', data: [58, 49, 38, 23, 27, 68, 38, 35, 7, 64, 65, 31] },

{ name: 'Fun 2', data: [8, 6, 34, 19, 9, 7, 17, 25, 14, 7, 10, 32] },

{ name: 'Fun 3', data: [67, 60, 66, 32, 61, 54, 13, 50, 16, 11, 47, 28] },

{ name: 'Fun 4', data: [8, 9, 5, 40, 13, 19, 58, 21, 47, 59, 23, 46] },

],

groupBy: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],

},

</script>

<template>

<div style="height: 400px">

<gl-stacked-column-chart

:bars="bars"

:group-by="groupBy"

presentation="stacked"

x-axis-type="category"

x-axis-title="January - December 2018"

y-axis-title="Commits"

/>

</div>

</template>

Design specifications

Color, spacing, dimension, and layout specific information pertaining to this component can be viewed using the following links:

Pajamas UI Kit →

Related

Charts

Last updated at:

Wednesday, July 15, 2026 at 12:21 PM
