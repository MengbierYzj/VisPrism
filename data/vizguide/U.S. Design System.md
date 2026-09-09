# U.S. Design System

Source: https://designsystem.digital.gov/components/data-visualizations/


## principle

- Simplicity

Prefer common visualization types.

Use data visualizations types that your target audience understands. When the level of the audience's data literacy is unknown, stick to well-used types (like line and bar charts) for explanatory visualizations.

Don't try to do too much.

Limit the 'big idea' expressed in a visualization to a central theme. Use no more than two or three concepts to reduce the cognitive load placed on the audience.

Use color with care.

Simplify color selection and don't reuse colors for different variables or within a particular variable. If you are finding this difficult, it may indicate too many concepts are present for a single visualization. When selecting colors, be sure to meet contrast requirements.


- Lossless representation

Avoid embedded information.

Avoid embedding information as part of an image. Provide a textual representation of axis values and labels, and provide the ability to get a tabular representation of the underlying data.

Reduce interaction.

Even simple interactions have a usability cost. Your audience shouldn't be required to interact with a visualization to understand its message. Presuming the ability to use a mouse to hover over page elements eliminates portions of the audience from the full experience.

Clarity of intent

Provide context-sensitive explanations.

Data visualization authors should consider the audience's experience when providing the background for the information they're sharing. Provide explanations or summaries that make sense to the target audience not just the author.

Get to the point.

If the visualization is intended to explain a specific point, don't leave the audience guessing as to the conclusion they're meant to draw.

Clearly state the author's intended message as text.

This avoids unintended ambiguity and helps the audience understand the visualization's intention.

- Accessibility

Solve for individual impacted groups, and be specific in your solutions.

Provide equivalent access.

Semantic headings and descriptions that provide the author's stated intent support assistive technologies and deliver a clear message to across audiences.

Screen readers might have difficulty reading content within an SVG. Provide an screen-reader accessible data table of the information represented in your visualization using the class

usa-sr-only

. When providing accessible equivalent, you can hide the visualization using the attribute

aria-hidden="true"

. The information in both of the example charts on this page is made accessible to screen readers with a visually-hidden table.

Note:

This is not always a sufficient alternative for complex data sets.

Provide equivalent facilitation.

Access to the underlying data provides an alternative affordance for consuming the same information, but a data table does not provide an equivalent narrative to a visualization.

Increase accessibility by providing additional information that the visualization communicates (like trends or a statistical summary) in plain text, using a screen reader–only class like

.usa-sr-only

.

Focus on manual testing.

Become familiar with testing tools and browser plugins. But only manual testing can check context and intent. The use of automated or mechanical checks can verify the presence of tags, not the proper content.

Choose an accessible charting tool.

There are many charting tools available, but not many adequately support accessibility. When using a 3rd-party tool, look for features such as:

Support for accessible patterns and colors

Sonification as a audio tool for visual impairment and analysis

## Line charts

Line charts are ideal for depicting trends in data over time using a continuous line.

Guidance

In addition to the general guidance above, the following line chart guidance applies:

Line charts origin should start at zero, unless clearly noted.

If high contrast color selection is not an option, the usage of discrete dash or datapoint styles distinguishes lines without relying upon color.

Example line chart

Search interest in Franklin D. and Theodore Roosevelt for the first week of March, 2020

Search interest in Franklin D. Roosevelt has been consistently higher than Theodore Roosevelt. Numbers represent search interest relative to the highest point on the chart for the given region and time. A value of 100 is the peak popularity for the term. A value of 50 means that the term is half as popular. A score of 0 means there was not enough data for this term.

March 1

March 2

March 3

March 4

March 5

March 6

March 7

Franklin D. Roosevelt

47

87

91

86

100

78

39

Theodore Roosevelt

30

50

46

42

46

39

22

Source:

Google Trends

What we did in our line chart example

There is a clear summary.

Users may not understand some narrative objectives from a graphic alone. The visualization also explains what the chart intends to communicate in plain language.

The lines are visually distinct from each other.

One is a solid color, and the other uses both a dash pattern and a color contrast between the line and the indicators. The indicators can also be triangles, squares, or other simple shapes. Typically, multiple indicator shapes and textures are most useful when comparing more than three data sets.

The graphic is hidden from screen readers.

Because the data set is fairly simple, non-visual users will be able to read the same data in the form of data table that's hidden from visual users but accessible to screen readers. If the data were more complex, we might consider using a 3rd party charting tool with support for accessibility as described above.

Original data linked.

We linked back to the original source data for the line chart.




## Bar charts

Bar charts are ideal for displaying categorical data.

Guidance

In addition to the general guidance above, the following bar chart guidance applies:

When displaying multi-variant data:

It is important to use discrete, high contrast colors or textured fill. This accommodation differentiates variables for audiences with visual impairments like color blindness or low vision.

The use of stacked bar charts for multi-variant data can be used if it is important to communicate the sum of the data set.

Example bar chart

The five most-visited national parks of 2019

Of the 62 parks with the designation "national park" as part of their official title, these were the top five. The Great Smoky Mountains National Park was the most-visited park by more than a factor of two.

Top 5 most visited Nation Parks

Park

Visits (in millions)

Great Smoky Mountain National Park

12.5

Grand Canyon National Park

5.87

Rocky Mountain National Park

4.7

Zion National Park

4.5

Yosemite National Park

4.5

Source:

National Park Service

What we did in our bar chart example

There is a clear summary.

Users may not understand some narrative objectives from a graphic alone. The visualization also explains what the chart intends to communicate in plain language.

Used a single color for the bars.

The bars are the same color because the data is categorically the same (visits) for each national park.

The graphic is hidden from screen readers.

Because the data set is fairly simple, non-visual users will be able to read the same data in the form of data table that's hidden from visual users but accessible to screen readers. If the data were more complex, we might consider using a 3rd party charting tool with support for accessibility as described above.

Original data linked.

We linked back to the original source data for the line chart.

Bar chart accessibility practices

