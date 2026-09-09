# Dell

Source: https://www.delldesignsystem.com/patterns/chart-customization/  
Related: https://www.delldesignsystem.com/data-visualization/ddv-overview

## Elements

Dell Design System guidance for customizing existing charts or building new charts aligned with Dell’s data-visualization foundations. The page is component-oriented and includes axes, legends, tooltips, plot area, responsive layout, and chart-selection rules.

## Axes and scale

- The y-axis normally represents quantitative values (quantity, sales, totals); the x-axis normally represents categories or time. Labels should concisely explain how the data is measured.
- Axis maximums should contain the highest value. Choose readable increments (for example, increments of 10 for a 0–100 range) and avoid a scale so large that meaningful changes disappear.
- Gridlines should match the scale defined by the x- and y-axes; do not use gridlines that imply a different measurement interval.

## Legend and series

- Use legend markers that map labels to the corresponding series. A single-series chart may not need a legend if title and axes are sufficient.
- Use a distinct categorical color for each series; do not reuse the same color for two series in one chart.
- Interactive legends may isolate a series. On hover, the selected series is emphasized and other series are muted.

## Tooltips and interaction

- The data-visualization tooltip is activated by hover or keyboard focus on desktop and by press on mobile.
- Use a consistent tooltip layout. For multiple series sharing an x-position, a multi-series tooltip groups the values and follows legend order, helping users compare without chasing overlapping marks.
- Interactive legends and tooltips should preserve focus and provide keyboard access.

## Plot area and layout

- Use a consistent chart container and internal padding. Dell’s examples use 24 px padding in standard layouts and additional right-side space when values are not aligned to the grid at small sizes.
- The legend moves below the x-axis on smaller viewports. Charts are responsive and should preserve readable labels and spacing.

## Chart selection

- Start from the analytical goal: trends are suited to line charts; parts of a whole to pie or donut charts; status/performance to gauges; comparisons and relationships to the corresponding bar, scatter, or other chart type.
- Give every chart a clear title and concise axis descriptions. The title states what the chart displays; axis labels explain how the data was collected and read.

## Related component guidance

- Dell’s gauge guidance uses semantic colors for healthy, warning, and danger states, but allows labels and color order to be customized for the use case.
- Dell also provides a table view so users can inspect or export exact chart data; this is important for accessibility and screen-reader navigation.

## Area Chart
Simple area charts use connected data points to show trends over time. The area below the plotted line is filled to give a sense of volume.
Usage

A simple area chart is used to display a single data series, allowing you to focus on changes in values over time. These changes should be measured using a zero baseline for the y-axis.

### Color

Avoid using stoplight colors (red, yellow, green) to show that data has a positive or negative value.

See Foundations page for accent color palette.

Sizes

Avoid small grid sizes with a lot of data points. This will affect readability and can increase the time it takes to process the information presented.

### Layout

Data points on lines are plotted using a zero baseline for the y-axis.

There is no legend for the simple area chart, as it measures a single series.

Specifications

All area chart specifications are built into the component. This ensures consistency across products, ease of use, and accessibility.

Altering the component specifications could have negative effects, so this is not recommended.

Margins

Vertical margins are:

24 pixels to the left of the plot line.
32 pixels to the right of the plot line.
Horizontal margins are:

24 pixels tall above the chart title.
24 pixels tall below the plot area.
32 pixels tall between the plot area and the chart title.
24 pixels tall between the legend and the plot area.

## bar chart
### When to use

Simple bar chart	Simple bar charts compare data of individual categories side by side.
Stacked bar chart	Stacked bar charts compare values of subcategories to the total values of primary categories.
Grouped bar chart	Grouped bar charts compare data of multiple categories side by side.

### Anatomy
Heading: includes the chart’s title and optional subtitle. Use subtitles when additional context is necessary.
Y-axis label: defines the data you are measuring. Commonly, this is revenue or quantity.
Y-axis value: represents the incremental measurements for plotted data. This will determine the height of each bar.
Category label: defines the main category each group belongs to. Commonly, this is quarter, year, or month.
Subcategory value: represents the subcategory each group belongs to. Its values are commonly the intervals in which measurements occur. This will determine the location for each group on the x-axis.
Bar value label: presents an always visible value for each bar.
Bar: visually indicates the data value of a subcategory. The height of a bar is relative to its value on the y-axis.
Plot area: shown as a grid within the bar chart, where data is displayed.
Container: houses the chart and all accompanying elements including the legend. The container aligns to grid to determine the chart’s size within in.

### Usage

Use simple bar charts to show data of individual categories side by side. They are helpful for comparing differences among subcategories in single data series and are commonly used for ordering and ranking categories by their numeric values.

### Ordering
When ordering categories, start with the lowest value on the left and list in ascending order to the right. This aids in a better visual comparison of data in the series.

Ranking
Bar charts used for ranking should order categories from high to low or low to high depending on the focus of the ranking.

### Color

Use the same color for all bars in a simple bar chart. This will keep the user focused on the values and won’t confuse the categorical representation.

Avoid using stoplight colors (red, yellow, green), as they are inherently associated with positive and negative values.

Review the categorical color palette for more information.

Categorical palette

Categorical colors help users distinguish nonnumerical data across categories that do not have an inherent correlation. These are provided in sequence to optimize contrast for accessibility and should not be reordered at implementation. The sequences provided are determined by the number of series or colors needed to uniquely display data within charts. These accommodate up to 4 series, 5 to 12 series, and 13 to 20 series.

Blue 900
#002A58
Orange 700
#A64600
Teal 500
#0EA0A9
Berry 800
#7F234F
Blue 500
#1282D6
Orange 700
#A64600
Teal 500
#0EA0A9
Berry 700
#A8396F
Blue 900
#002A58
Orange 500
#C96100
Teal 900
#044E52
Berry 500
#CB548D
Blue 700
#0063B8
Orange 800
#7D2E00
Teal 700
#0B7C84
Berry 800
#7F234F
Blue 500
#1282D6
Orange 700
#A64600
Teal 500
#0EA0A9
Berry 700
#A8396F
Blue 900
#002A58
Orange 600
#B85200
Teal 900
#044E52
Berry 600
#BA467D
Blue 800
#00468B
Orange 500
#C96100
Teal 800
#076469
Berry 500
#CB548D
Blue 700
#0063B8
Orange 800
#7D2E00
Teal 700
#0B7C84
Berry 900
#511230
Blue 600
#0672CB
Orange 900
#4F1A00
Teal 600
#0D8E97
Berry 800
#7F234F
Note that the 13 to 20-color sequence has some color conflicts, as many shades are used together. As such, this sequence should be used only in extreme cases when more than 12 series must be displayed on the same chart. It is not generally advised to represent so many lines within a chart, as it can introduce cognitive overload.

Semantic palette

The semantic palette is used to communicate health status. Color is not a universal experience, and usage should not rely on color alone to convey meaning. Including an icon, label, or both can increase user understanding.

Green 500
#5D8C00
Green 700
#436F00
1px inner stroke
Yellow 300
#E6AC28
Yellow 500
#B36F00
1px inner stroke
Red 700
#BB2A33
Red 800
#8C161F
1px inner stroke
