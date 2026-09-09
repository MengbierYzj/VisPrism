# Shopify

Source: https://polaris.shopify.com/design/data-visualizations  
Current readable mirror: https://polaris-site-prod-kit.shopify.prod.shopifyapps.com/design/data-visualizations

## principle
An effective data visualization strikes the right balance between the five core traits: accuracy, intuitiveness, engagement, focus, and data granularity. It’s important to be intentional about which of these you focus on, and which are less important, in order to answer your specific question in the best way for your target audience. Understanding these traits help you choose between the many ways to visualize data by giving you a language for evaluating a visualization's effectiveness.

Accuracy
Accuracy is about how faithfully the visualization matches the original data set. How much accuracy is needed to send your message across? A high level of accuracy may not always be needed to convey a trend or a pattern.

Intuitiveness
Intuitiveness is about the ease of interpreting the visualization. Will merchants immediately understand what’s being represented, or will they need instructions? More intuitive is usually better, but sometimes it comes at the cost of flexibility.

Engagement
Engagement is about how much attention the visualization attracts at a glance. Is it the star of the show, or does it sit in the background? More engagement is not always better—sometimes the best visualization is one that plays a supporting role.

Focus
Focus is about how merchants’ attention is directed. Is one pattern or trend surfaced more prominently than others, or are there several trends that are given equal weight? Highly focused visualizations decrease cognitive overload, but restrict the breadth of the message you are able to convey.

Data Granularity
Data granularity is about the level of detail of the data set presented in the visualization. More granular means more data points, and possibly more cognitive processing, but less granular is less detailed. The right level of data granularity depends entirely on the specific question you’re trying to answer and the audience you’re communicating to.

## Axes and labels

All standard charts that show quantitative data have 2 axes that should be labeled for clarity.

Labelling should be outside and separate from the data area. This ensures the user understands the range of the data without taking focus away from the data.
Ensure that all labels are clear and accurate in what they represent. Use simple and short language.

## Granular guidelines
Axis lines
Axis lines should be used as a guideline to show quantitative data, yet be unobtrusive.

Skipping labels
Labelling the tick marks on both the y-axis and x-axis helps the visualization become more clear in what it represents.

X-axis Abbreviations
Shopify uses standard abbreviations for months and weekdays in order to reduce clutter in visualizations.

Use 12 hour format for time, with lowercase letters (12am, 6pm)
Use the first three letters for days of the week (Sun, Mon)
Use the first three letters for months (Feb, Mar)
For specific days, use the format ‘day + month’ (10 Apr, 11 Apr)
For specific months, use the format month + year (Apr 2011, May 2017)

Y-Axis Abbreviations
Shopify uses standard monetary abbreviations for the y-axis to reduce clutter.

X-axis Labelling conventions
Labels should be clear and concise

Y-axis Labelling conventions
Labels should be clear and concise.

## Color

Color in data visualization has a very specific meaning. The data visualization color palette provides specific colors that can be used alone or in a group, depending on the intent.

Single data series
Use when there is a single data series. For example, a bar chart, column chart, or a single line chart.

Single comparison to past
This is used when the data set is being compared to to its past values. For example, total sales by month, this year, compared to last year. In this case, the current value will be purple and the past value will be grey.

Multiseries data
Used when there are multiple data sets to compare. For example, a multiseries line chart. Go down the list as the number of datasets increase.

Biased
Used when certain data need is displayed in a negative or positive light. For example, showing positive or negative change relative to a reference value.

## Chart types

### Horizontal bar charts
Bar charts are used for comparing discrete categories. Use a bar chart when there is a constraint to the number of data points that can appear on the visualization, otherwise it becomes hard to scale.

Best used for
Showing discrete categories of data, like {products} vs {sales}.

Don’t use
When the number of data points can exceed 6. In this case, use a table.

Bar chart labels
Label each bar with what it’s displaying, as well as the value. For more best practices, visit axis and label conventions.

Include a label on each bar. If the bar is too small, include it outside of the bar.

Include a label on top of each bar to display what data it’s showing.

Color
Use one color for all bars.
Give negative bars 60% opacity.
don't Use multiple colors for the bars.

Bar positioning
Make sure the bars are proportional in width, roughly twice the size of the space between the bars.
Make the width of each bar about twice as wide as the space between them.
don't Make the bars too skinny.

### Vertical column charts
Column charts are used to show change over time, trends, and individual data points. Use column charts for when the number of data points is fewer than 30, or else use a line chart.

Best used for
Showing continuous data like sales per hour, or orders per month
Showing smaller granularities of time (hourly, daily, weekly, and monthly)
Don’t use
When the number of data points can exceed 31. In this case, use a line chart.

Color
All bars should be the same color.

Bar positioning
Make sure the bars are proportional in width, roughly twice the size of the space between the bars.

### Line charts
A line chart is created by connecting a series of data points together with a line. Line charts are good to show change over time, comparisons, and trends. Use line charts when the number of data points is more than 30.

Best used for
Showing continuous data like sales or orders over time
Showing larger granularities of time (yearly, or quarterly)
Spotting overall trends and shapes of data
Axis and labelling
Set up the chart area using the axis and labelling guidelines

Multiline charts
Line graphs work well when multiple datasets need to be compared. Use the color palette to select colors.

## Accessibility
An important part of designing clear visualizations is making data accessible to everyone.

Provide options
Merchants with vision issues might have trouble understanding visual presentations of data, even with assistive software.

Merchants with dexterity or motor issues might have trouble using interactive visualizations that depend on fine motor control.

Others might simply have trouble understanding data presented in a chart or graph.

To support the needs of different merchants, always provide multiple formats for data visualizations.

Do
Let merchants access their data in multiple formats. For charts and graphs, it’s often helpful to offer the same content in a data table that’s either on the same page or on a related page that’s easy to discover.

Don't
Provide data visualizations in only one format.

Use of color
Color is critical for visualization, but can cause issues for merchants with color blindness and low vision. Color should be used in a way that supports the interpretation of visual information for all merchants, including those with visual issues.

Do
Ensure that text, line, bar, and other colors have sufficient contrast against their background.

Use colors that can be distinguished from each other to support merchants with different forms of color blindness.

Don't
Require that merchants are able to see color to understand the information provided in the chart or graph.

