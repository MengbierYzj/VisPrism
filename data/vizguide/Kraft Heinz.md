# Kraft Heinz — Delish Design System

Source: https://delish.supernova-docs.io/latest/about/delish-design-system-lWrOQArP  
Data-visualization section: https://delish.supernova-docs.io/latest/data-visualization/chart-guidelines/part-to-whole-aZUPf3Es

## principle

storytelling
clear
inclusive
accurate
curious
actionable


## chart selection
Which chart do I use?
When trying to figure out which chart to use, ask yourself who your audience is and what you want the data to show. Sometimes a bar chart really is the best chart to tell the story.

Charts can be categorized by four different objectives: comparison, correlation, distribution and composition. This is not a one-size-fits-all solution to picking the right chart. Designing effective, story-telling products is more than just choosing the right chart for the data set. This Chart Selection guidance should help you get started when trying to decide the best chart for your data.

 

Comparison
Do I need to see the difference or similarity of metrics within the data?
Charts that show comparison between data sets show patterns and trends quickly. Comparison shows similarities or differences. This chart function helps to highlight patterns and outliers.

Other charts: Pie/Donut, Heatmap, Stacked bars, Bubble, Dot plots, Waterfall, Butterfly, Lollipop, Waffle


Correlation
How do these metrics relate to or affect each other?
Charts that show the connection between two or more variables in the data or how one variable might affect other variables.

Other charts: Sankey, Heatmap, Dumbbell, Venn



Distribution
How do these metrics tend to behave, either over time or in relation to themselves?
Distribution can show the frequency and how a specific metric spreads out or clusters. A distribution of a metric plots a collection of information to find out how it spreads and to understand if there’s any interaction between the variables.

Other charts: Line, Treemap, Heatmap, Bubble, Scatterplot, Boxplot, Stacked Area, Area, Dot Plot
 

Composition
How do the individual metrics make up or compare to the whole metric?
Composition charts present each individual metric as compared to the whole

Other charts: Progress bars, Bullet charts, Bullet, Waffle, Marimekko, Gauge


## Bar charts
What are they?
Bar charts display data using (you guessed it) bars that are proportional to the values they represent. There are several different types of bar charts depending on the data and the story the chart is telling. Bar chart data is categorical and answers the question “how many” are in each category.

Bar chart | horizontal and vertical
 


Horizontal and vertical bar charts show bars with lengths proportional to the values they represent. One axis of the chart shows categories being compared and the other represents the value.


Grouped bar chart | horizontal and vertical

These grouped bar charts compare values across different categories within each group.


 

Lollipop

Lollipop charts are similar to bar charts, but are made up of a line and circle rather than a bar. The center of the circle at the end of the lollipop marks the category value.

 


Butterfly

Butterfly charts show two categories or two groups of categories on a y-axis on opposing sides of the vertical axis. The chart helps readers quickly identify differences between the two sides.

 

Histogram

Histograms are charts that show the distribution of a variable as a series of bars. Each bar typically covers a range of values called a bin or class. A bar’s height indicates the frequency of data points with a value in the bin.

 

Ribbon

Ribbon charts illustrate change in rankings among categories over time. Each category is represented by a segment within stacked bars. These segments are connected across the bars to form continuous ribbons. The segments are ordered from the largest at the top to the smallest at the bottom, allowing for a clear visual representation of how each category's rank evolves.

Waterfall

Waterfall charts show how a starting value changes through a series of positive and negative adjustments, leading to a final value. They are useful for breaking down financial data, like showing how different factors add up to a total. Because waterfall charts have a complex visual structure, they can cause confusion for audiences. Consider using bar charts, line charts or stacked bar charts to represent changes over time before using a waterfall chart


 

Consider other chart types before using

Consider other chart types before using charts with this label. They might be appropriate, but less familiar charts are often misinterpreted—book office hours with the data viz team if you’re unsure.

 

Bar Chart Guidelines
X & Y Axis
Include an x-axis on column charts to establish a baseline. For bar charts, include a y-axis. Don’t let the columns or bars float without the clearly defined baseline.

Ref to 88:486
 

Zero baseline
Columns and bars always should start at a zero baseline. If the columns/bars are similar in height and the differences are important but indistinguishable, consider a line chart, where a zero baseline isn’t required, or use columns/bars but plot the change or percent change.

Ref to 88:550
 

Data over time
When showing data over time, try use columns instead of bars. Time is easier to read left to right than up and down. If you must plot time this way, start with the most recent data point at the top.

Ref to 88:607
 

Sort, sort, sort!
Sort the bars (or columns) by greatest to least or least to greatest unless there is a category order you must follow. Don’t put the bars (or columns) in a random order.

Ref to 88:681
 

Gridlines or direct labels
Use one or the other, you generally don't need both.

Ref to 88:754
 

Use one color if bars show the same categorical data
If for example, the categories are showing ROI values for 4 quarters, use the same color for the four bars.
 

Use color to highlight the most important aspect of the story
Use gray to de-emphasize bars that are less important.


## line chart

What are they?
Line charts show trends and change over time for one or more categories. The horizontal axis often shows time and the vertical axis shows what is being measured. Two other line chart types are area charts and slope charts.

 


 

 

Line

Line charts plot numeric values for categorical data as a line that often shows a progression through time.

 

Find your platform components here:

Figma | Tableau | PowerBI

 

 

Area

Area charts are similar to line charts but the area between the line and the x-axis is filled. Area charts emphasize magnitude of change.

 

Find your platform components here:

Figma | Tableau | PowerBI

 

 

Slope

Slope charts are line charts that show the change between two points, usually over time. They are useful for showing year over year change, or comparing different categories’ change between those times.

 

Find your platform components here:

Figma | Tableau | PowerBI


 

 

Consider other chart types before using

Consider other chart types before using charts with this label. They might be appropriate, but less familiar charts are often misinterpreted—book office hours with the data viz team if you’re unsure.

 

 

 

Line Chart Guidelines
Gridlines
Provide enough gridlines to help readers interpret the data points. Use logical increments. Don’t overcrowd the chart with more gridlines than necessary and avoid gridlines in unusual increments.


 

No spaghetti charts!
In most cases, only include up to 4 lines in a single chart. Try to never use more than 6 lines. It is difficult to see each line or make comparisons when there are many lines in the chart. Consider small multiples instead.


 

Line thickness
Lines should be thick enough to stand out from the gridlines, but thin enough to show detail in twists and turns. Lines that are too thick can hide the small changes between the data points.


 

Use a different line treatment or background to show future data
If you are showing future data, indicate that change to the reader. One way is to use a dashed line in the same color as the past data. Make sure to add a legend entry for that dotted line. A solid line in a lighter shade could work as well. An alternative is to shade and label the background.


 

Use color to highlight the most important aspect of the story
If one of the lines in a chart is more important than the others, you can use color to make that single line stand out from the others. Gray can be used to deemphasize lines that are shown for context but are not part of the main story.


## plot

What are they?
Scatterplots, dot plots, dumbbell charts and box and whisker plots are related types of visualizations that use dots to represent individual data points on one or two axes.

 


 

 

Scatterplots

Scatterplots show the relationship between two measures. Each dot is plotted based on their x and y values. They are useful for showing patterns and trends.

 

Find your platform components here:

Figma | Tableau

 

 

Dot plots

Dot plots represent data points along a single axis representing a single metric.

 

Find your platform components here:

Figma | Tableau

 

 

Dumbbell

Dumbbell charts are dot plots that show the difference between two sets of data points.

 

Find your platform components here:

Figma | Tableau

 

 

 

Box and Whisker

Box and whisker plots compare distributions of multiple data sets. They illustrate medians and percentiles and are useful when comparing that information.

 

Find your platform components here:

Figma | Tableau


 

 

Consider other chart types before using

Consider other chart types before using charts with this label. They might be appropriate, but less familiar charts are often misinterpreted—book office hours with the data viz team if you’re unsure.

 

 

 

Plot Chart Guidelines
Don’t forget to sort
Sort the chart to help show patterns. Sort by greatest to least (or vice versa) for one set of dots or sort by the difference between the dots. Avoid using a random order for the categories.


 

Don’t overcrowd the dumbbell
Show two dots, or at most three, in a dumbbell chart. Dumbbell charts generally show the differences between points and too many dots for each category makes the chart hard to read.


 

Use transparency and outlines to help show overlapping dots
When data points overlap, use transparent dots with outlines rather than solid dots to improve chart legibility.


 

Don’t use bubbles for metrics with small differences
It is difficult to see small size differences among circles. Consider using bubbles only if you expect differences among the data values to be large enough to be distinguishable. Also keep in mind that circles can’t be a negative size, so if you’re considering using bubbles for a third metric make sure that metric remains positive.


 

Don’t use a single box and whisker plot
If you have just a single data set, consider using a histogram or some other chart type. A simpler chart like a dot plot may work better than a box and whisker plot if medians and percentiles are not critical to the data story.


## part to whole
Part-to-whole charts
What are they?
Part to whole charts show the distribution and relationship of individual components that make up a whole. The whole can be shown as circle (where the parts are wedges), a bar (made up of segments), a rectangle (made up of other rectangles) or areas under a curve, depending on the chart type. Examples of these charts include stacked bar charts, pie charts, donut charts, treemaps and stacked area charts.

 


 

 

100% Stacked bar

100% Stacked bar charts show data using horizontal or vertical bars. The length of each segment of the bar represents a different category’s contribution to the total. The length of all the segments combined together represents the whole.

 

Find your platform components here:

Figma | Tableau | PowerBI

 

 

Stacked bar

Stacked bar charts can also show contributions to the whole where the segments represent actual values rather than a percentage of a whole.

 

Find your platform components here:

Figma | Tableau | PowerBI

 

 

Pie

Pie charts display parts of the whole as wedges of a pie. All of the wedges added together make a full circle and add up to 100%.

 

Find your platform components here:

Figma | Tableau | PowerBI

 

 

Donut

Donut charts are similar to pie charts but they have a hole in the center.

 

Find your platform components here:

Figma | Tableau | PowerBI

 

 

Gauge

Gauge charts look like speedometers or fuel gauges and show progress toward a target or goal. They are generally circular or semi-circular and divided up into segments that show ranges of categories leading up to target or goal.

 

Find your platform components here:

Figma | PowerBI


 

 

Treemap

Treemaps are charts used to visualize large, hierarchical data sets. They are comprised of nested rectangles and can use the color and size of the rectangle to convey information.

 

Find your platform components here:

Figma | Tableau | PowerBI


 

 

Progress bar

Progress bars are are stacked bar charts where one section of the bar shows progress toward a target or goal and the second section shows how much of the goal is unmet.

 

Find your platform components here:

Figma | Tableau | PowerBI

 

 

Bullet chart

A bullet chart monitors progress to a goal or target and clearly shows when a category value is above or below it.

 

Find your platform components here:

Figma | Tableau

 

 

Consider other chart types before using

Consider other chart types before using charts with this label. They might be appropriate, but less familiar charts are often misinterpreted—book office hours with the data viz team if you’re unsure.

 

 

 

Part-to-whole chart guidelines
Include all parts of the whole in pies
If you’re making a pie chart, make sure you include all of the parts and that they add up to 100%. If you don’t, the chart may have unexpected proportions. For example, a user expects to see 50% corresponding to half a pie but if parts are left out, 50% could be larger than half. If you’re showing only selected parts of the whole, use a stacked bar instead.


 

Avoid pie charts for comparison
It is difficult to compare segments in pie charts. If you need to compare two or more “wholes” use stacked bars or an area chart.


 

Not too many segments
When using a pie chart, try not to use more than 4 or 5 segments. If you need to show more than that, consider a stacked bar and also think about ways to simiplify the data. Can you combine segments? Can you highlight the most important segments somehow?


 

Use colors that are easily differentiable
Make sure that colors used for the wedges are easy to tell apart. This is especially important if you’re using a legend rather than direct labeling.


 

Use color to highlight the most important category if there is one
Color is an effective way to highlight the most important segment of a pie chart. If you’re using color to highlight a segment, make sure one that color is more prominent than the others.


 

Use shades of gray to de-emphasize segments that are less important
If highlighting a single segment in a pie chart, shades of gray are a good choice for less important segments.


## color

Color plays a pivotal role in data visualization, as it can convey information, emphasize patterns, and create visual hierarchy. Careful selection and application of colors can enhance the clarity and impact of data representations, making complex information more accessible and engaging to the audience.

 

Core
Our core palette refers to a set of colors chosen to represent different categories or groups within a dataset. They typically consist of a range of colors that are easily distinguishable from each other.

 

Colors / Data viz / Core
#295cad
Blue
#a2aeb5
Gray
#b94431
Red
#05a3b1
Teal
#0b3873
Ocean
#529c74
Green
#df9f37
Yellow
 

Semantic
This palette is a set of colors used to represent and distinguish different trajectories in a visualization. They often represent the movement or progression of entities over time or space, and assigning distinct colors to each trajectory helps viewers track and identify individual paths within the visualization.

 

On light backgrounds
Colors / Data viz / Semantic / Light bkgd
#529c74
Positive
#b94431
Negative
#df9f37
Notice
 

On dark backgrounds
Colors / Data viz / Semantic / Dark bkgd
#37bb65
Positive
#cc2e48
Negative
#df9f37
Notice
 

Sequential
Blue
#133a77
#295cad
#6f94ce
#9ebbe6
Gray
#36383a
#646b6f
#a2aeb5
#d1dbe2
Red
#460f05
#8c2e20
#b94431
#cf8a7e
Teal
#063f44
#136a73
#05a3b1
#80d0d7
Ocean
#071e39
#0b3873
#5a74cb
#9ab2ff
Green
#08362a
#1d6953
#529c74
#87c3a9
Yellow
#563b10
#a06a14
#df9f37
#ffd592
 

