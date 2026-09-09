# Carnegie Mellon Univeristy

Source: https://www.cmu.edu/brand/brand-guidelines/data-viz.html


## Purpose

In order to effectively communicate the story represented in the data, choose charts that best convey the insight you wish to provide and apply styling carefully to support that message. Also, consider the context and the preferences of your audience.

### Goal

- What are you trying to convey? Limit the visualization to one main theme with two or three supporting concepts to limit cognitive load and increase usefulness.

### Audience

- How will the users of your visualization engage with it? Lay out the visualization and apply styles with device type, method of communication and cultural preferences in mind. If possible, test visualizations with users as part of the development process.

### Data

- What type of information are you using the data to show? Additionally, what charts are your audiences most comfortable with? As much as possible, stick to common chart types (such as bar and line charts), especially when the audience's level of data literacy is unknown.

### Accessibility

Web accessibility

is a priority and takes into consideration all disabilities that impact access to the web, including auditory, cognitive, neurological, physical, speech and visual. Limitations can be permanent (such as colorblindness), temporary (such as a broken arm) or situational (such as a noisy, distracting environment). To design data visualizations that are accessible to as many users as possible, it is especially important to consider the experience of people who have a vision deficiency or use technology such as screen readers, Braille keyboards or keyboard-only navigation.

 Color

- Data visualizations often utilize color as a representation or to tell a story. Approximately 4.5% of people have some form of color-vision deficiency, so color can’t be the only way to explain or inform. Using the recommended color palette, which is designed to provide the best contrast, along with using appropriate chart types will aid in comprehension for all users.

Text

- Including a title that is short but descriptive enough to explain the visual and adding labels to important data points are key steps to creating an accessible data visualization. A summary will ensure that the takeaway from your data visualization is easily understood and consistent across all users.

### Style

#### Color

Color can be a very useful way to supplement and support the information conveyed in charts and text. In order to account for all disabilities that impact access to data visualizations, apply best practices to your selection and use as few colors as possible.

Colors also hold certain meanings, both cultural and emotional, so it is important to choose your color palette with intention.

PowerBI Color Palettes

Additional color best practices

categorical Core

CMU Red

#c41230

196, 18, 48

Dark Gray

#4d5051

77, 80, 81

When sharing data that compares the university or university-related groups or organizations with other universities, groups or organizations, use CMU Red to represent CMU. Use Dark Gray to represent all other values. Use white text for data labels and marks that appear over these colors.

Make sure to consider your audience and the cultural implications of using the color red, particularly if you are portraying financial data. If your visualization is directed to an internal audience, use a color from the secondary palette rather than red.

Categorical secondary

Teal

#008285

0, 130, 133

Blue

#043673

4, 54, 115

Green

#00853e

0, 133, 62

Dark Green

#1f4c4c

31, 76, 75

Highlands Sky Blue

#007bc0

0, 123, 192

Weaver Blue

#182c4b

25, 44, 75

Skibo Red

#941120

149, 17, 32

Black

#000

0, 0, 0

Use in conjunction with the categorical core palette. Use white text for data labels and marks that appear over these colors.

Sequential Primary

Highlands Sky Blue

#007bc0

0, 123, 192

#458ac8

#679ad0

#83aad8

#9dbae0

#b6cbe8

#cfdcf0

#e7edf7

White

#ffffff

Sequential Secondary

Gold Thread

#fdb515

253, 181, 22

#ffbe41

#ffc75f

#ffd07b

#ffd995

#ffe2b0

#ffecca

#fff5e4

White

#ffffff

Divergent

Gold Thread

#fdb515

253, 181, 22

#ffc35c

#ffd28f

#fbe1c0

#f1f1f1

#c4d2e5

#96b4d9

#6397cd

#### Typography

Font sizes and styles are important for creating a hierarchy on the page and among elements. Choosing the appropriate typography will guide the user to the important information and emphasize key points. Additionally, it is essential in allowing a person utilizing screen reader technology to navigate the page.

When using Tableau, the typeface Tableau Sans should be used for all text elements. For other data visualization tools, use the typeface Helvetica.

-Text Element

Size

Weight

Section dividers

20pt

Regular

Title

15pt

Bold

Subtitle

13pt

Regular

Axis labels

12pt

Data labels

11pt

Regular*

Notes/annotations

12pt

Links

Regular, underlined**

*Bold only data points you want to call attention to

**Links should be displayed in Carnegie Red

#### Charts Types

Guidelines for the most common chart types are listed below. In circumstances requiring additional chart types, first, consider the audience and their familiarity with various representations of data and apply the guiding principles as outlined above.

Bar

Allows the comparison of data across categories either vertically or horizontally

Can be stacked to show proportions of datasets

Unless paired with other charts that use the same color for categories, use one color to represent all categories compared against the same measure

Show ordinal data in ascending or descending order

Always start at a zero baseline for the x-axis

Line

Represents the change in one or more values over time

Scatter Plot

Shows an x-y relationship between data points and can use a trend line

Dot size can convey additional information

Use a baseline of zero for the x-axis and y-axis

Use color to identify patterns and outliers

Pie & Donut Charts

Highlights portions of a whole dataset

Best when limited to 2-3 slices

Most useful when emotionally conveying a sense of size

To more clearly compare percentages, a stacked bar chart is preferred

Heatmap

Use color density to show concentration patterns for a single variable

Map

Use the sequential color palette to show a single value by geographical location

Limit the chart to regions included in the data

Avoid decorative shading or colors and instead leverage color and size to show data variations

#### Text Elements

Data visualizations can show a story, but it is just as important for the text that accompanies your image to tell the same story on its own.

People utilizing technology such as screen readers or who primarily use keyboard navigation rely on excellent text elements in graphs and charts in order to understand and navigate the visualization.

Be careful when utilizing the hover feature in Tableau. If you want to direct users to important data, it should be indicated with text within the graph where all users will be able to access it. Use ‘hover’ to provide a method to drill down to supporting data.

Do:

Make it large enough to read

Size it according to importance and hierarchy

Use horizontal text for best readability

Don't:

Use text that isn't necessary and could cause more confusion such as extra labels or too many annotated data points

Use vertical text

##### Titles

The titles you include in your chart or graph should summarize the data visualization. They should be simple but summarize the story your chart or graph is telling.

##### Labels

Use labels on the chart or graph to highlight important values or data points.

For readability, use commas to separate values and limit the use of decimal places

Round numbers minimize clutter and improve readability

For axis labels, skip those with regular intervals to avoid clutter in your visualizations

Standard abbreviations should be used to make it easier to view the data (Ex.: Sun, Mon, Tue for days of the week or Jan, Feb, Mar for months)

##### Captions, Notes and Summaries

Always write captions, notes and summaries in such a way that they concisely explain the visual.

##### Legends

When possible, avoid using a legend. Instead, incorporate your data labels directly into the data visualization. Legends can add confusion to all users because going back and forth between the legend and the chart or graph is more difficult visually and for people utilizing assistive technology.

