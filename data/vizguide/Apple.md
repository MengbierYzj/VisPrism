# Apple

Source: https://developer.apple.com/design/human-interface-guidelines/charts  
Related: https://developer.apple.com/design/human-interface-guidelines/charting-data

## Design philosophy

An effective chart highlights a few key pieces of information in a dataset, helping people gain insights and make decisions. For example, people might use a chart to:

- Learn how upcoming weather conditions might affect their plans.

- Analyze stock prices to understand past performance and discover trends.

- Review fitness data to monitor their progress and set new goals.

## Anatomy
- A chart comprises several graphical elements (grid line, plot area, mark, axis,tick, axis value label(tick label)) that depict the values in a dataset and convey information about them.
A mark is a visual representation of a data value. You create a chart by supplying one or more series of data values, assigning each value to a mark. To specify the style of chart you want to display — such as bar chart, line chart, or scatter plot — you choose a mark type, such as bar, line, or point (for guidance, see Marks). The general task of depicting individual data values in a chart is called plotting, and the area that contains the marks is called the plot area.

- To depict a value, each type of mark uses visual attributes that are determined by a scale, which maps data values like numbers, dates, or categories to visual characteristics like position, color, or height. For example, a bar mark can use a particular height to represent the magnitude of a value and a particular position to represent the time at which the value occurred.

- To give people the context they need to interpret a chart’s visual characteristics, you supply descriptive content that can take a few different forms.

- You can use an axis to help define a frame of reference for the data represented by a set of marks. Many charts display a pair of axes at the edges of the plot area — one horizontal and one vertical — where each axis represents a variable like time, amount, or category.

- An axis can include ticks, which are reference points that help people visually locate the position of important values along the axis, such as a 0, 50%, and 100%. Many charts display grid lines that each extend from a tick across the plot area to help people visually estimate a data value when its mark isn’t near an axis.

- You also have multiple ways to describe chart elements to help people interpret the data and to highlight the key information you want to communicate. For example, you can supply labels that name items like axes, grid lines, ticks, or marks, and accessibility labels that describe chart elements for people who use assistive technologies. To provide context and additional details, you can create descriptive titles, subtitles, and annotations. When needed, you can also create a legend, which describes chart properties that aren’t related to a mark’s position, such as the use of color or shape to denote different value categories.

## Marks

- Choose a mark type based on the information you want to communicate about the data. Some of the most familiar mark types are bar, line, and point; for developer guidance on these and other mark types, see Swift Charts.

- Bar marks work well in charts that help people compare values in different categories or view the relative proportions of various parts in a whole. When used to help people understand data that changes over time, bar charts work especially well when each value can represent a sum, like the total number of steps taken in a day.

- Line marks can also show how values change over time. In a line chart, a line connects all data values in one series of data. The slope of the line reveals the magnitude of change between data values and can help people visualize overall trends.

- Point marks help you depict individual data values as visually distinct marks. A set of point marks can show how two different properties of your data relate to each other, helping people inspect individual data values and identify outliers and clusters.

- Consider combining mark types when it adds clarity to your chart. For example, if you use a line chart to show a change over time, you might want to add point marks on top of the line to highlight individual data points. By combining points with a line, you can help people understand the overall trend while also drawing their attention to individual values.


## Axes

- Use a fixed or dynamic axis range depending on the meaning of your chart. In a fixed range, the upper and lower bounds of the axis never change, whereas in a dynamic range, the upper and lower bounds can vary with the current data. Consider using a fixed range when specific minimum and maximum values are meaningful for all possible data values. For example, people expect a chart that shows a battery’s current charge to have a minimum value of 0% (completely empty) and a maximum value of 100% (completely full).

- In contrast, consider using a dynamic range when the possible data values can vary widely and you want the marks to fill the available plot area. For example, the upper bound of the Y axis range in the Health app’s Steps chart varies so that the largest number of steps in a particular time period is close to the top of the chart.

Define the value of the lower bound based on mark type and chart usage. For example, bar charts can work well when you use zero for the lower bound of the Y axis, because doing so lets people visually compare the relative heights of individual bars to get a reasonable estimate of their values. In contrast, defining a lower bound of zero can sometimes make meaningful differences between values more difficult to discern. For example, a heart rate chart that always uses zero for the lower bound could obscure important differences between resting and active readings because the differences occur in a range that’s far from zero.

Prefer familiar sequences of values in the tick and grid-line labels for an axis. For example, if you use a common number sequence like 0, 5, 10, etc., people are likely to know at a glance that each tick value equals the previous value plus five. Even though a sequence like 1, 6, 11, etc., follows the same rule, it’s not common, so most people are likely to spend extra time thinking about the interval between values.

Tailor the appearance of grid lines and labels to a chart’s use cases. Too many grid lines can be visually overwhelming, distracting people from the data; too few grid lines can make it difficult to estimate a mark’s value. To help you determine the appropriate density and visual weight of these elements, consider a chart’s context in the interface, the interactions you support, and the tasks people can do in the chart. For example, if people can inspect individual data points by interacting with a chart, you might use fewer grid lines and light label colors to ensure the data remains visually prominent.



## Titles, labels, and explanation

- Write descriptions that help people understand what a chart does before they view it. When you provide information-rich titles and labels that describe the purpose and functionality of a chart, you give people the context they need before they dive in and examine the details. Providing context in this way is especially important for VoiceOver users and those with certain types of cognitive disabilities because they rely on your descriptions to understand the purpose and primary message of your chart before they decide to investigate it further.

- Summarize the main message of your chart to help make it approachable and useful for everyone. Although a primary reason to use a chart is to display the data that supports the main message, it’s essential to summarize key information so that people can grasp it quickly. For example, Weather provides a title and subtitle that succinctly describe the expected precipitation for the next hour, giving people the most important information without requiring them to examine the details of the chart.

## Best prcactice
- Establish a consistent visual hierarchy that helps communicate the relative importance of various chart elements. Typically, you want the data itself to be most prominent, while letting the descriptions and axes provide additional context without competing with the data.

- In a compact environment, maximize the width of the plot area to give people enough space to comfortably examine a chart. To help important data fit well in a given width, ensure that labels on a vertical axis are as short as possible without losing clarity. You might also consider describing units in other areas of the chart, such as in a title, and placing a longer axis label, such as a category name, inside the plot area when doing so doesn’t obscure important information.

- Help people notice important changes in a chart. For example, if people don’t notice when marks or axes change, they can misread a chart. Animating such changes can help people notice them, but you need to highlight the changes in other ways, too, to ensure that VoiceOver users and people who turn off animations know about them. For developer guidance, see UIAccessibility.Notification (UIKit) or NSAccessibility.Notification (AppKit).




## Color and visual hierarchy

As in all other parts of your interface, using color in a chart can help you clarify information, evoke your brand, and provide visual continuity. For general guidance on using color in ways that everyone can appreciate, see Inclusive color.

- Avoid relying solely on color to differentiate between different pieces of data or communicate essential information in a chart. Using meaningful color in a chart works well to highlight differences and elevate key details, but it’s crucial to include alternative ways to convey this information so that people can use your chart regardless of whether they can discern colors. One way to supplement color is to use different shapes or patterns to depict different parts of data. For example, in addition to using red and black or red and white colors, Health uses two different shapes in the point marks that represent the two components of blood pressure.

- Aid comprehension by adding visual separation between contiguous areas of color. For example, in a bar chart that stacks marks in a single row or column, it’s common to assign a different color to each mark. In this design, adding separators between the marks can help people distinguish individual ones.
