## Cartesian charts
These use two axes to show data and help users see patterns or compare values.

Line chart: Visualizes one or many series of data, with an emphasis on how the data changes over time.

Bar chart: Visualizes one or many series of data, with an emphasis on the total amount of each data point.

Mixed chart: Visualizes different, but related, series of data on a single chart.

Scatter chart: Visualizes the relationships between data in two dimensions.

Bubble chart: Visualizes the relationships between data in three dimensions, using position for two variables and bubble size for a third.

Area chart: The area chart visualizes two or more series of data. Through stacked data series, it emphasizes the part-to-whole relationship of data over a period of time.

Pie and donut charts
Pie and donut charts display portions of a whole unit so users can compare data points from a total set. A donut chart also includes a summary metric in the center of the chart.

Pie chart: A pie chart helps users see the relationship between different data metrics in a data set.

Donut chart: A donut chart is a variant of a pie chart with its center removed.

## Objectives
The objective of data visualization is for users to be able to quickly and clearly derive meaning from a set of data. Data visualization supports four common objectives:

- Identifying trends: Users want to understand how a metric or set of metrics is changing over time, particularly if the changes correspond with other events in the user's services.

- Identify aberrations/anomalies: Users want to spot deviations from a normal or expected range, often the significant increase or decrease of a particular metric.

- Comparison: Users want to identify commonalities or divergences between two or more metrics.

- Investigate problems: Users have been notified of a problem or found one during a review or investigation, and use a visualization to better understand what happened.


## Data type
Data can generally be divided in two main types: numeric (any quantitative measure) and categorical (qualitative data, usually expressed with text labels). Identify the data type your user needs and select the chart that best supports the data.

### Numeric
- Individual units of measurement, typically arrayed over a time or date range.

For example: A bar chart that shows the number of errors logged by an application over the past three months.

### Categorical
- Qualitative delineation between sets of data. Categories can be a ranked or ordered series of data (such as high, medium, and low severity). Or they can be grouped by type, which has no standard order (such as different types of databases).

For example: A stacked bar chart that shows the total number and severity of alerts over the past seven days.


## Time period
The time period of a chart is the way time is depicted in the chart's data and display.

### Continuous
Shows multiple data points over multiple points or periods of time.

For example: A line chart that shows CPU usage of an instance over the course of 7 days.

### Snapshot
Shows metrics from a single point or period of time.

For example: A pie chart that shows the number of different alert types logged in a specific day.


## Number of metrics
The number of metrics shown in a data visualization should be sufficient for the user to understand the visualization, but not too many that it becomes confusing or overwhelming.

There are two levels of metrics that should be considered:

### Data points
- Individual numerical points of data charted in the visualization. On charts that use X and Y axis, such as line charts, a data point is plotted on a specific X and Y coordinate. On charts that use polar coordinates, such as pie charts, the data point is represented as a segment of the total area. For example: The temperature of a CPU at a specific time.

The number of data points shown should reflect the granularity users need to properly interpret the visualization.

### Data series
- Data points that are related to each other and grouped to form a series. Some charts, such as line or bar charts, might have multiple data series on the same visualization. Other types of charts, such as pie charts, have only a single data series. For example: A set of CPU temperatures logged once a second for a minute.

The number of included data series shouldn’t clutter the chart and overwhelm the user. Refer to the guidance for each chart type for the number of data series to show.


## General guidelines

###Do
Use appropriate meta information, such as titles, labels, and the legend, to describe the chart’s intention and ensure users understand how the data displayed relates to other information on the page.
Include the minimum number of metrics and information users need to complete their desired task. Refer to the guidelines for each chart type for specific guidance.
Avoid showing too many metrics on a single chart. If you’re over the recommended number of metrics, consider showing multiple charts or grouping metrics.
When showing a large number of metrics on a single chart, include data filters so users can decide which metrics to show.
Ensure chart placement and size fits within the visual hierarchy of the page. When using multiple charts at the same level of importance, they should have consistent sizing.
Minimize the number of charts displayed in a single view to avoid visual overload.
Use a consistent and accessible color palette for your data visualization. For more information, see data visualization colors for guidance.

### Don't
Don't use data visualization for decoration.
Never display data in a way that could mislead users to a false conclusion. For example, if the Y axis of a line or bar chart does not start at 0, changes are exaggerated, potentially creating a misleading impression of significant changes over time.


## Accessibility guidelines

### General accessibility guidelines
- Follow the guidelines on alternative text and Accessible Rich Internet Applications (ARIA) regions for each component.

- Make sure to define ARIA labels aligned with the language context of your application.

- Don't add unnecessary markup for roles and landmarks. Follow the guidelines for each component.

- Provide keyboard functionality to all available content in a logical and predictable order. The flow of information should make sense.


### Component-specific guidelines
- Refer to the accessibility guidelines for different types of charts.

- Use an accessible color palette for visualizations. Refer to data visualization color guidance.

## Color
Generic categorical palette
Categorical color palettes are best used to represent qualitative data with discrete categories or data series with no standard order. Use this palette for data that does not need a specific color association. It uses 5 hues (blue, pink, teal, purple, and orange), and has been ordered to be visually distinguishable to each other when used together. Follow the order of the palette to determine what colors to use based on the number of data series a chart includes.

The palette includes 50 values, ordered by a rotating pattern that allows for contrast between adjacent values. To automate this pattern, follow the development guidelines for building custom palettes. However, when designing a chart, be mindful of the total number of data series displayed at once. Having too many data series and colors will make it harder for users to read a chart and harder to recognize each color from one another. Consider displaying only up to 8 data series for a line chart or bar chart, and up to 5 data points for a pie chart or donut chart. The color tokens in this palette can be themed and are marked as themeable in the table below.Palette is listed below
#688ae8
#c33d69
#2ea597
#8456ce
#e07941
#3759ce
#962249
#096f64

## Threshold colors
Thresholds can be effective accent elements to provide additional context to a line chart or bar chart. Use the following colors for threshold lines based on what the threshold represents. They can be used on a chart with any color palette. The color tokens in this palette can be themed and are marked as themeable in the table below.
General guidelines

### Do
Be consistent with colors when presenting the data series across multiple charts.
Place charts only on the default container background color for both light and dark mode.
Use a 2px divider to separate segments on stacked bar charts, pie charts, and donut charts for higher contrast between colors.
Consider displaying only up to 8 data series for a line chart or bar chart, and up to 5 data points for a pie chart or donut chart.

### Don't
Don't use colors specific to data visualization for UI elements. For those purposes, follow the guidelines for colors foundation. 
Don’t apply a different color across multiple attributes from the same data series. Minimize the number of colors used on a given chart. For example, for a bar chart that represents the total cost of a resource by month, do not use a different color for each month. Use one color instead. 
Don’t apply colors for decoration purposes.

### Accessibility guidelines

General guidelines
All colors have been selected to meet the minimum 3:1 contrast against the container background.

Provide multiple formats to a chart when possible, to give users the ability to select their preferred format in case one format may be easier for them to recognize colors over another. 

For example: A user may prefer reading a chart as a bar chart over a line chart because of the use of wider rectangles over thinner lines.

### Color-blind safe palette
There is no such thing as a true “color-blind safe” palette as everyone’s ability to perceive color is unique to them. Though color is a primary element for data visualizations, it should not used as the only method of communicating what the data on a chart represents. Make sure that other methods of identification is also available on a chart for recognition. Such as:

Labels, such as those that directly point to each slice on a pie chart or a popover that labels a line when a user interacts with it.

Filters that allow users to select specific data series to focus on.