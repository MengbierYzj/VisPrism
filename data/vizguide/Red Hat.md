# Red Hat

Source: https://www.patternfly.org/charts/about/


## anatomy
- Title: Titles should be left-aligned and appear above your chart.
- Axis labels and scale values: We recommend using tick marks to clearly mark scale values on the y-axis. The text for axis labels and scale values should be 12px font in standard text color. All scale values should be equally distributed across the axis and the axis label should fall outside the scale values, centered with the axis line.
- Legends: We recommend using legends when charts include more than one variable and therefore use more than one color. When datasets are overlapping, an interactive legend can be used. If space is not available to display names of horizontal and vertical axes, a legend must be added instead. The legend should list the colors that each variable obtains and the name of the variable. The text on the legend should be 14px size and standard text color. They can either be placed left-aligned to the right of the chart or centered below the chart.
- Chart tooltip: A tooltip will appear on hover over certain elements of a chart, like bars in a bar chart or segments in a donut chart. Chart tooltips should display the specific values related to the element the user is hovering over.




## Chart types
Area chart: Use to show (potentially multiple) trends over a continuous scale (usually time).
Bar chart: Use to show and compare categories and their respective data point/value. Bar charts can be plotted vertically or horizontally. The axis that labels the bar is the category, the axis that marks the end point of the bar displays the data points/values.
Stacked bar chart: Use to show and compare categorical data of more than one variable. Can be plotted vertically or horizontally.
Vertical bar charts (category on the horizontal x axis): Use to show a progression of the categories (or sequential variables). The most common bar chart.
Horizontal bar charts (category on the vertical y axis): Use to show nominal variables. Allows for more space for category labeling.
Bullet chart: Use as an extension to the bar chart to measure data with thresholds and static ranges.
Donut chart: Use to show the relationship of a set of values to a whole or to show progress completion as a percentage. Donut charts are best used to display data with a small number of categories (example: 2-5 categories). Use the middle of the chart to highlight a data point.
Donut utilization: Use to show utilization for an object as a percentage.
Donut utilization with threshold: Use to show utilization for an object as a percentage in relation to threshold values.
Line chart: Use to compare several data sets or to show data changes over a period of time. Line charts work best when small changes exist within the data.
Pie chart: Use to show percentages or proportional data. Can be used to show up to five or more data points.
Sparkline: Use to show how values change over time for multiple sets of data. Sparkline charts offer an alternative to the line chart when multiple lines need to be plotted. Axis values are not labeled, but a tooltip can be used to display the value at a given point.

## color
Primary colors
Primary colors are those displayed most frequently across your application screens and components. Our primary color is called "PatternFly blue", which is used across PatternFly's components. PatternFly blue should change upon hover.

Default
--pf-v5-global--primary-color--100
Hover
--pf-v5-global--primary-color--200
