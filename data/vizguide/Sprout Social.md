# Sprout Social

Source: https://seeds.sproutsocial.com/patterns/dataviz/


## Description
Charts are a visual way to display data in order to highlight trends and social activity that may be impacting a user's business.

Formatting
When creating charts, try not to plot more than four items per chart.

Data density
The max number of metrics allowed on a single chart should be no more then ten. The ideal state for readability is four.

## charts
Charts should sit on a white background with a gray border. The Sprout Social or Bambu logo should be located in the bottom-left and a URL in the bottom-right.
Layout specifics will vary by visualization type. Documented guidelines for data include:
Bar charts
Line charts
Pie charts
Tables

### Line
A line chart is created by connecting a series of data points together with a line. Line charts are good to show change over time, comparisons and trends.

Line weight: 3px
Used for single metrics or comparisons.
use round off points instead of sharp edges

Bar / Horizontal Bar
Bar charts are used for comparing discrete categories. Use a bar chart when there is a constraint to the number of data points that can appear on the visualization; otherwise, it becomes difficult to scale.

do
Sort data from highest to lowest unless requirements dictate otherwise.
do
Right-align topic labels in bar charts to the y-axis. Numerical values should be left aligned with the end of a given topic’s data bar.

Stacked Area
Used for multiple metrics. Cumulative totals.

Multi Select
Line chart with an interactive key.
Maximum of 20 items
Donut
Donut charts are best to use when you are trying to compare parts of a whole (ie x% out of 100%). They do not show changes over time. They work best when the data points are simple and comparisons between different percentages are dramatic.

If needed use 1px white line separations between segments for clarity.
Large and small variations available.
Two small sized donut charts are equal to the height of one large donut chart.
Because donut charts do not lend well to heavy text usage, keys are a good way to display topic labels.

do
Use to convey five or fewer discrete categories that add up to 100%.
do
Use a 1px stroke between sections of the pie if it helps add visual clarity between similar colors.
don't
Use donut charts when there are so many data points that it is difficult to make distinctions between segments.
don't
Use donuts charts when the size of all the segments are too similar (24%, 25%, 25%, 26%, for example).

## color
Colors
It’s all about contrast! Colors should be distinct to allow the viewer to quickly and easily distinguish data points.

do
Use shades of the same hue to visually relate data.
do
Use contrasting colors to differentiate between pieces of data.
don't
Networks colors should not be used in data visualization.


Rotation
When creating charts, use complementary color schemes to ensure that the data can easily be differentiated. Colors should be applied in the following order:

data viz
Teal 500
#08c4b2
JS
Sass
CSS
Android
Purple 700
#6f5ed3
JS
Sass
CSS
Android
Pink 700
#ce3665
JS
Sass
CSS
Android
Yellow 500
#ffcd1c
JS
Sass
CSS
Android
Blue 500
#3876e3
JS
Sass
CSS
Android
Magenta 500
#db61db
JS
Sass
CSS
Android
Green 500
#59cb59
JS
Sass
CSS
Android
Orange 500
#fc8943
JS
Sass
CSS
Android
Red 700
#db3e3e
JS
Sass
CSS
Android
Teal 900
#026661
JS
Sass
CSS
Android
Purple 400
#a193f2
JS
Sass
CSS
Android
Pink 900
#931847
JS
Sass
CSS
Android
Yellow 900
#944c0c
JS
Sass
CSS
Android
Blue 900
#0c3f89
JS
Sass
CSS
Android
Magenta 900
#6c2277
JS
Sass
CSS
Android
Green 900
#006b40
JS
Sass
CSS
Android
Orange 900
#962c0b
JS
Sass
CSS
Android
Red 400
#ff7f6e
JS
Sass
CSS
Android
Green 700
#0ca750
JS
Sass
CSS
Android
Yellow 800
#ba7506
JS
Sass
CSS
Android
Brand campaigns and initiatives
If you’re creating data visualizations for a brand campaign or initiative that has a specific color palette, you don’t need to use this color system. However, you should make sure that the colors you use have sufficient color contrast on the color wheel (avoid analogous color schemes).

Best Practices
do
Show the axis lines where the data will be representedDO: Axis Lines
don't
Extend the axis lines to fill the full width of the content areaDON'T: Axis Lines
do
Do always include a zero on the Y axis
don't
Manipulate axes in such a way that the data becomes exaggerative
don't
Use inconsistent intervals (skipping certain months, quarters or other data points).
do
Use standard abbreviations for labelsDO: Abbreviations
don't
Slant labels to make them fitDON'T: Abbreviations
do
Center the chart Key below the chartDO: Key
don't
Left or Right Align the chart Key or place it above the chart