# Office for National Statistics

Source: https://style.ons.gov.uk/category/data-visualisation/


## principle

Showing the important comparison:Design your chart in a way that clearly shows the important trends to the user.
Keep charts simple:Aim to make your chart as simple as possible while still giving users the necessary context to understand the data.

## chart type

Overview
Picking the right chart type is important for communicating the insights in your data.

When choosing a chart type, consider both the type of data you have and the specific relationships or trends you want to highlight.

If you need further help, or have any questions, contact digitalcontent@ons.gov.uk 

The code to build the chart examples are provided in the chart component pages in the Design system section.

Common relationships in data visualisations
There are eight relationships that data visualisations commonly convey. Consider the important trend or comparison you want to convey to the user and use the chart type that best illustrates it.

Some chart types can illustrate different relationships depending on the data used. For example, a bar chart might show magnitude, parts of a whole, distribution, or change over time.

Correlation
The relationship between two variables.

Deviation
The difference between a value and an average or another value.

Distribution
How data values are spread for a variable.

Geography
The pattern of data across different locations or areas.

Magnitude
The size of values.

Parts of a whole
The relative sizes of components within a whole.

Ranking
The position of data within a hierarchy or scale.

Time
How a value changes over time.

Choose simple and familiar charts
Use simple charts that will be familiar to users whenever possible.

Complex or unfamiliar charts can be difficult to interpret and may obscure the relationships you are trying to display.

Charts that show multiple relationships
Some chart types can display more than one relationship at the same time.

For example, an area chart can show both the parts of a whole and how they change over time. A connected-dot plot can illustrate both the magnitude of two variables and their deviation.

Choose a chart type that best illustrates the most important relationship you want to convey.

Charts showing multiple relationships are often less clear than charts focused on a single relationship.

If necessary, use multiple charts to present different relationships, as two simple charts can be more effective than one complex chart.

Consistent baselines
When comparing data, it is often easier to interpret charts where components start from a consistent baseline.

For example, it can be difficult to compare individual components in stacked charts if they do not share a common starting point.

Consider using charts like line charts, where users can easily compare trends.

Example of a chart without a consistent baseline for categories
In this example, it is hard to compare the relative size of components and data may be misinterpreted.

Open this example in a new tab

Example of a line chart with a consistent baseline for categories
In this example, it is easier to compare the relative size of components and see the trend described in the chart title.

Open this example in a new tab

Exceptions to using consistent baselines
Using a consistent baseline may not always the best choice.

A stacked chart may be more effective when dealing with large value differences, when precise comparison is less important, or when you want to show the size of a total.

Start with the big picture
Where you do need to use more a complex visualisation, it can be helpful to provide a simple overview of the data first. This helps build the users’ understanding of the data before diving into more detailed or complex charts.

For example, if comparing the breakdown of housing types for different regions, first present the national breakdown before looking into regional differences.

Stock or flow data in change over time charts
Time series data can be categorised as either stock data or flow data.

Understanding whether you have stock or flow data can guide your choice of chart type. For example, a line chart might show total public debt (stock data), while a column chart shows the monthly budget deficit (flow data).

Stock data
This data shows the value of something at a specific point in time, for example, total wind turbines in the UK. It remains constant until updated.

Stock data is typically better suited to line or area charts.

Flow data
This data measures occurrences or rates of change over a specific time interval, for example, number of wind turbines built in the UK last year. It resets to zero at the start of each time interval.

Flow data is often best represented with a column chart, where each column represents a specific time period.


## color
Overview
Using the right colours will make sure your data visualisation is accessible, clear and intuitive. For certain charts, colour is a way to differentiate between categories of data. Examples of this are line charts and stacked bar charts.

Some visualisations use colour to represent quantitative (numerical) values. Examples are choropleth maps and heatmaps. Colour can also be used to highlight data within a chart.

There are several important things to consider when choosing the colours in your data visualisation, such as:

using sufficient contrast with the background colour
ensuring that the colours are suitably different from one another; this is especially important for users with colour vision deficiency
using colour in a way that is intuitive and helps to convey the meaning of the data
limiting the number of colours used; users may find it difficult to tell the difference between colours if too many are used
When to use a single colour
Certain chart types do not need colour to differentiate between categories. An example of this is a bar chart, where a single colour is used to represent the data.

At the Office for National Statistics (ONS), we use Ocean blue when only one colour is needed.

Ocean blue
#206095
CSS variable
--ons-color-ocean-blue
CMYK
93, 51, 6, 4
Where categories in a chart are grouped under subheadings, use the same colour for all groups.

An exception to this is where different colours are used for different categories or groups in multiple charts in a publication. Use the same colours for each group in each data visualisation to ensure consistency across the release.

Read more in Use consistent colours 

Highlighting
For charts with a single main colour, use a different colour to highlight a category or interesting data point.

In the following example, a highlight colour helps the user to quickly see the UK data in the two charts:

Open this example in a new tab

When using colour to highlight a category, it is sometimes useful to provide an annotation explaining this.

Read more about how to use annotations in our annotations guidance

In Chartbuilder, the default highlight colour is orange. Use this to highlight the important data.

In charts created in other tools, use grey to show less important categories and use Ocean blue or other colours from our standard category colour palette to highlight important data

Multiple colours
Certain charts need multiple colours to differentiate between categories of data. Examples of this are line charts with more than one series and stacked bar charts.

In the following line chart example, different colours are used to differentiate between the lines:

Open this example in a new tab

In the following stacked bar chart example, different colours are used to show the segments within each bar:

Open this example in a new tab

Avoid using too many categories and colours. The more colours there are, the harder it is for users to perceive differences between them, especially for users with a colour vision deficiency.

!
In the Chartbuilder tool, some alternative chart types will not be possible. Never use more than nine colours. Make sure colours are not repeated for more than one category within the same chart.

Always use five colours or fewer in your data visualisations to help users perceive the differences between colours

Standard category colour palette
More colours can be used when using a colour scale to show ordered data. Read more in Categories with an order 

To reduce the number of colours needed you may need to:

show fewer series
group categories into larger groups, for example, several small categories could be grouped into an “other” group
consider which categories are shown on the axis
consider an alternative chart type
More guidance on how to keep charts simple is available on the principles page

When using multiple colours to differentiate between categories, use the standard category colour palette.

Ocean blue
#206095
CSS variable
--ons-color-ocean-blue
CMYK
93, 51, 6, 4
Spring green
#a8bd3a
CSS variable
--ons-color-spring-green
CMYK
26, 1, 100, 10
Beetroot purple
#871a5b
CSS variable
--ons-color-beetroot-purple
CMYK
44, 99, 26, 21
Coral pink
#f66068
CSS variable
--ons-color-coral-pink
CMYK
0, 74, 48, 0
Dark leaf green
#05341a
CMYK
90.38, 0, 50, 79.61
Sky blue
#27a0cc
CSS variable
--ons-color-sky-blue
CMYK
86, 8, 0, 0
Night blue
#003c57
CSS variable
--ons-color-night-blue
CMYK
100, 39, 0, 63
Mint green
#22d0b6
CSS variable
--ons-color-mint-green
CMYK
66, 0, 40, 0
Lavender purple
#746cb1
CSS variable
--ons-color-lavender-purple
CMYK
64, 60, 0, 0
!
The Chartbuilder tool currently uses a different standard colour palette. 

Highlight colour
The highlight colour is used in Chartbuilder to call attention to a certain category in a chart. It should ideally only be used with the blues and greens of the primary chart palette, as it is a complementary colour.

Highlight orange
#f39431
CSS variable
--ons-color-highlight-orange
CMYK
0, 50, 85, 0
Adjustments for text
Three of the chart colours fall below the 3:1 colour contrast ratio threshold. This is to help with colour differentiation in the charts.

We use darker versions of these colours for text labels on charts.

Any text where the colour contrast ratio is below 4.5:1 should only be used for large text .

Spring Green adjusted for chart text
#8a9b2e
CSS variable
--ons-color-spring-green-text
CMYK
11, 0, 70, 39
Mint green adjusted for chart text
#1aa590
CSS variable
--ons-color-mint-green-text
CMYK
84, 0, 13, 35
Highlight orange adjusted for chart text
#f56927
CSS variable
--ons-color-highlight-orange-text
CMYK
0, 57, 84, 4

