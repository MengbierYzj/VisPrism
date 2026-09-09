# Tractie (NS Dutch Railways)

Source: https://tractie.ns.nl/2e23992f3/p/6056d7-data-visualisation  
Design-system context: Tractie is the enterprise design system of Nederlandse Spoorwegen (NS).

## principle
Data visualisation
A visual way to present data, to make it easier to understand.

## Anatomy
Chart title (optional): Describes the chart in a short sentence.

Axis labels: Explains what data is being shown on each axis and in what units.

Axis titles (optional): Provides context, clearly describing what the categories and values represent.

Grid lines: Provides reference lines, improving readability and precision.

Baseline: The zero-point on the axis from which bars grow.

Legend (optional): Explains the meaning of each category color. Do not include a legend for single-category charts. Be aware that legends may not be accessible for users with color blindness. Tooltips should be provided as an additional cue.



## Types
The chart types below represent recommended visualisation patterns. Tractie does not provide coded chart components. Teams can apply these guidelines when styling their own library.

Single bar chart — used to compare values across several categories, showing progression or changes over time.

Stacked bar chart — used to show parts of a whole, similar to pie charts but easier to read.

Grouped bar chart — used to compare multiple data series side-by-side within categories.

Line chart — used to show trends or changes over time.

Area chart — used to show how values evolve over time and contribute to a whole.

Donut chart — used to show parts of a whole, with emphasis on the overall total.

Figma tip: We provide a Bar Chart component in Figma as a reference.

## Best practices
Axis
Intervals: Use consistent, clear and simple intervals. 

Start at zero: Most charts should start the Y-axis at zero to avoid distorting values.

Non-zero baseline: Primarily for line charts, a non-zero Y-axis is acceptable when the goal is to show the shape of change rather than absolute values. For example, when values cluster in a narrow range and starting at zero would compress all variation into an unreadable graph. Do not use a non-zero baseline to make a small difference look larger than it is.

Number of categories
Try to limit the amount of categories to 5. This improves readability and makes it easier to understand.
Be aware that having more then 5 categories could make a chart more difficult to read or understand.
Density of bar charts
Use at least 8px spacing between single bars. For grouped bars, use at least 16px spacing between groups and 2px spacing within groups.

Set bar width to 16px, with at least 8px of spacing between bars.
Do not reduce bar width below 16px or spacing between bars below 8px, as this makes them harder to distinguish. To increase data density, show fewer bars or use a different chart type (like an area chart).
For bar groups, set the bar width to 12px, with at least 16px spacing between groups and 2px between bars within a group.
Bar chart orientation
Use a horizontal bar chart when the number of bars exceeds the available width or when labels are too long for a vertical layout.

##  colors
With our design tokens you can apply colors in data visualisations. Use chart tokens for colors that represent the data. Use border and content tokens for axes and text.  

Categorical colors
Use categorical colors to distinguish multiple categories within a chart. Don't reorder these colors, since they are in an optimized sequence for contrast and accessibility. These colors also pass 3:1 color contrast ratios on all elevated backgrounds in light and dark mode.

Name
Light
Dark
color.chart.category-1
Use for data visualizations. Follow the numbered sequence.
{color.palette.blue.600}
{color.palette.blue.300}
color.chart.category-2
Use for data visualizations. Follow the numbered sequence.
{color.palette.teal.400}
{color.palette.teal.500}
color.chart.category-3
Use for data visualizations. Follow the numbered sequence.
{color.palette.yellow.700}
{color.palette.yellow.400}
color.chart.category-4
Use for data visualizations. Follow the numbered sequence.
{color.palette.pink.600}
{color.palette.pink.300}
color.chart.category-5
Use for data visualizations. Follow the numbered sequence.
{color.palette.purple.400}
{color.palette.purple.500}
color.chart.category-6
Use for data visualizations. Follow the numbered sequence.
{color.palette.teal.600}
{color.palette.teal.200}
color.chart.category-7
Use for data visualizations. Follow the numbered sequence.
{color.palette.yellow.900}
{color.palette.yellow.100}
color.chart.category-8
Use for data visualizations. Follow the numbered sequence.
{color.palette.pink.400}
{color.palette.pink.500}
Charts with a single color
Start with a single color. Only use the categorical colors when it's adding value. Different colors could clutter your application when there is no meaning for it. 

Use color.chart.category-1 for single color charts.

Use color.chart.category-1 as the single color. 
Don’t use multiple category colors when these colors don’t communicate any new information.
Semantic colors
Some colors have meaning within charts. We avoid those colors within the categorical chart colors to prevent confusion. When a color does need to communicate a success, warning or error state, use these semantic colors.

Be aware that these colors are not experienced the same way for everyone. Some people see colors different, which could result in a different interpretations of the same color. Always use a secondary way to communicate the meaning. Including an icon, label or another visual indicator could make a world of difference.

Name
Light
Dark
color.chart.neutral
Use to tone down elements in data visualizations.
{color.palette.gray.400}
{color.palette.gray.500}
color.chart.success
Use to communicate positive information in data visualizations.
{color.palette.green.500}
{color.palette.green.400}
color.chart.warning
Use to communicate caution in data visualizations.
{color.palette.orange.500}
{color.palette.orange.400}
color.chart.error
Use to communicate negative or critical information in data visualizations.
{color.palette.red.600}
{color.palette.red.500}
Use color.accent.gray.subtle when part of a graph is not filled. For example, when displaying a percentage. 

Be aware that this color does not pass 3:1 contrast ratio. Do not use it for communicating data.

Use color.accent.gray.subtle to emphasize the useful part.
Don't use color.chart.neutral when this data is not adding value.
Highlighting
Highlight an interesting data point by toning down less important data in a chart with color.chart.neutral.

Accessibility
Color contrast
All categorical and semantic colors pass 3:1 contrast ratios against all elevation backgrounds in light and dark mode.



Separate colors by a border or gap
It is important to have a border or gap between two colors. For two reasons:

For some people, two colors can be experienced as the same. By adding a border, they can still see both areas.

Chart colors don't pass 3:1 contrast ratios against each other. By adding a border, good contrast is ensured.