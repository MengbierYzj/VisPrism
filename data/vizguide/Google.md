# Google

Source: https://material.io/design/communication/data-visualization.html



## Principles

Data visualization is a form of communication that portrays dense and complex information in graphical form. The resulting visuals are designed to make it easy to compare data and use it to tell a story – both of which can help users in decision making.

Data visualization can express data of varying types and sizes: from a few data points to large multivariate datasets.
- Accurate
Prioritize data accuracy, clarity, and integrity, presenting information in a way that doesn’t distort it.
- Helpful
Help users navigate data with context and affordances that emphasize exploration and comparison
- Scalable
Adapt visualizations for different device sizes, while anticipating user needs on data depth, complexity, and modality.

## Types
Data visualization can be expressed in different forms. Charts are a common way of expressing data, as they depict different data varieties and allow data comparison.

The type of chart you use depends primarily on two things: the data you want to communicate, and what you want to convey about that data. These guidelines provide descriptions of various different types of charts and their use cases.

### Types of charts
#### Change over time
Change over time charts show data over a period of time, such as trends or comparisons across multiple categories.

Common use cases include:

Stock price performance
Health statistics
Chronologies

- Change over time charts include:

1. Line charts
2. Bar charts
3. Stacked bar charts
4. Candlestick charts
5. Area charts
6. Timelines
7. Horizon charts
8. Waterfall charts

#### Category comparison
Category comparison charts compare data between multiple distinct categories.

Use cases include:

Income across different countries
Popular venue times
Team allocations
Category comparison charts include:

1. Bar charts
2. Grouped bar charts
3. Bubble charts
4. Multi-line charts
5. Parallel coordinate charts
6. Bullet charts

#### Ranking
Ranking charts show an item’s position in an ordered list.

Use cases include:

Election results
Performance statistics
Ranking charts include:

1. Ordered bar charts
2. Ordered column charts
3. Parallel coordinate charts

#### Part-to-whole
Part-to-whole charts show how partial elements add up to a total.

Use cases include:

Consolidated revenue of product categories
Budgets

Part-to-whole charts include:

1. Stacked bar charts
2. Pie charts
3. Donut charts
4. Stacked area charts
5. Treemap charts
6. Sunburst charts

#### Correlation
Correlation charts show correlation between two or more variables.

Use cases include:

Income and life expectancy

Correlation charts include:

1. Scatterplot charts
2. Bubble charts
3. Column and line charts
4. Heatmap charts
#### Distribution
Distribution charts show how often each values occur in a dataset.

Use cases include:

Population distribution
Income distribution

#### Distribution charts include:

1. Histogram charts
2. Box plot charts
3. Violin charts
4. Density charts
#### Flow
Flow charts show movement of data between multiple states.

Use cases include:

Fund transfers
Vote counts and election results


Flow charts include:

1. Sankey charts
2. Gantt charts
3. Chord charts
4. Network charts
#### Relationship
Relationship charts show how multiple items relate to one other.

Use cases include

Social networks
Word charts


### Selecting charts
Multiple types of charts can be suitable for depicting data. The guidelines below provide insight into how to choose one chart over another.

#### Showing change over time

Change over time can be expressed using a time series chart, which is a chart that represents data points in chronological order. Charts that express...

Change over time can be expressed using a time series chart, which is a chart that represents data points in chronological order. Charts that express change over time include: line charts, bar charts, and area charts.

Type
of
chart	Usage	Baseline
value *	Quantity of time
series	Data type
Line chart	To express minor variations in data	Any value	Any time series (works well for charts with 8 or more time series)	Continuous
Bar chart	To express larger variations in data, how individual data points relate to a whole, comparisons, and ranking	Zero	4 or fewer	Discrete or categorical
Area chart	To summarize relationships between datasets, how individual data points relate to a whole	Zero (when
there’s more than one series)	8 or fewer	Continuous
* The baseline value is the starting value on the y-axis.

#### Bar and pie charts

Both bar charts and pie charts can be used to show proportion, which expresses a partial value in comparison to a total value. Bar charts,...

Both bar charts and pie charts can be used to show proportion, which expresses a partial value in comparison to a total value.

Bar charts express quantities through a bar’s length, using a common baseline
Pie charts express portions of a whole, using arcs or angles within a circle
Bar charts, line charts, and stacked area charts are more effective at showing change over time than pie charts. Because all three of these charts share the same baseline of possible values, it’s easier to compare value differences based on bar length.
- Do Use bar charts to show changes over time or differences between categories.
- Don’t use multiple pie charts to show changes over time. It’s difficult to compare the difference in size across each slice of the pie.


#### Area charts

Area charts come in several varieties, including stacked area charts and overlapped area charts: Overlapping area charts are not recommended with more than two time...

Area charts come in several varieties, including stacked area charts and overlapped area charts:

Stacked area charts show multiple time series (over the same time period) stacked on top of one another
Overlapped area charts show multiple time series (over the same time period) overlapping one another
Overlapping area charts are not recommended with more than two time series, as doing so can obscure the data. Instead, use a stacked area chart to compare multiple values over a time interval (with time represented on the horizontal axis).

-Do Use a stacked area chart to represent multiple time series and maintain a good level of legibility.

-Don’t use overlapped area charts as it obscures data values and reduces readability.

## Style

Data visualizations use custom styles and shapes to make data easier to understand at a glance, in ways that suit the user’s needs and context.

Charts can benefit from customizing the following:

Graphical elements
Typography
Iconography
Axes and labels
Legends and annotations

### Styling different types of data

Visual encoding is the process of translating data into visual form. Unique graphical attributes can be applied to both quantitative data (such as temperature, price, or speed) and qualitative data (such as categories, flavors, or expressions).

These attributes include:

Shape
Color
Size
Area
Volume
Length
Angle
Position
Direction
Density

### Expressing multiple attributes
Multiple visual treatments can be applied to more than one aspect of a data point. For example, a bar color can represent a category, while a bar’s length can express a value (like population size).

### Shape

Charts can use shapes to display data in a range of ways. A shape can be styled as playful and curvilinear, or precise and high-fidelity,...

Charts can use shapes to display data in a range of ways. A shape can be styled as playful and curvilinear, or precise and high-fidelity, among other ways in between.

Level of shape detail
Charts can represent data at varying levels of precision. Data intended for close exploration should be represented by shapes that are suitable for interaction (in terms of touch target size and related affordances). Whereas data that’s intended to express a general idea or trend can use shapes with less detail.

- Do
The bars in this chart have subtle rounded corners, ensuring that the top of the bar precisely measures the bar’s length.
- Don't
Don’t use shapes that make it hard to read a chart, such as bars with imprecise top edges.

### Color

Color can be used to differentiate chart data in four primary ways:

Distinguishing categories from one another
- Representing quantity
- Highlighting specific data
- Expressing meaning



### Accessibility
To accommodate users who don’t see color differences, you can use other methods to accentuate data, such as high-contrast shading, shape, or texture.

Applying text labels to data also helps clarify its meaning, while eliminating the need for a legend. See more in color contrast.

### Line

Chart lines can express qualities about data, such as hierarchy, highlights, and comparisons. Line styles can be styled in different ways, such as using dashes...

Chart lines can express qualities about data, such as hierarchy, highlights, and comparisons. Line styles can be styled in different ways, such as using dashes or varied opacities.

Lines can be applied to specific elements, including:

Annotations
Forecasting elements
Comparative tools
Confidence intervals
Anomalies

### Typography


Text can be used to label different chart elements, including:

Chart titles
Data labels
Axis labels
Legend
The text with the highest level of hierarchy is usually the chart title, with axis labels and the legend having the lowest level of hierarchy.

Scale category	Typeface	Font	Size
1. Chart title	Roboto	Regular	18pt
Chart subtitle	Roboto	Regular	14pt
2. Data label	Roboto	Regular	22pt
Sub-label	Roboto	Regular	14pt
3. Axis labels	Roboto	Regular	12pt
4. Legend labels	Roboto	Regular	12pt

Text weight
Headings and varying font weights can communicate which content is more (or less) important than other content in the hierarchy. However, these treatments should be used sparingly, with a limited number of typographic styles.


Labelled axis


A labelled axis, or multiple axes, indicates the scale and scope of the data displayed. For example, line charts display a range of values along both horizontal and vertical labelled axes.

Text orientation
Text labels should be placed horizontally on the chart so that they are easy to read.

Text labels should not:

Be rotated
Stacked vertically

Legends and annotation

Legends and annotations describe a chart’s information. Annotations should highlight data points, data outliers, and any noteworthy content. On desktop, it’s recommended to place a...

Legends and annotations describe a chart’s information. Annotations should highlight data points, data outliers, and any noteworthy content.