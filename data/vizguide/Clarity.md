# Clarity Design System

Source: https://clarity.design/documentation/charts

## Philosophy

Data visualization, often called charts, is the presentation of data in a graphical format. It helps communicate complex ideas in a clear and understandable way.

We visualize data to:

- Explain: answer a question in a visual format
- Explore: find patterns, trends and insights in data
- Monitor: check performance and focus on leading indicators

## Chart anatomy

- **Title:** concise and descriptive; provide enough context to understand the topic at a glance.
- **Axes:** the x-axis usually represents categories or time and the y-axis quantitative values. Label axes with units and use an appropriate scale; avoid unnecessary gridlines.
- **Labels and legends:** use readable labels close to the marks/axes. Place legends where they remain visible and do not obstruct the plot; every legend item must map clearly to its mark.
- **Tooltips:** use hover/focus to provide exact values, categories, or dates. Keep content relevant and readable with sufficient contrast; avoid overwhelming users.
- **Data table:** place a readable tabular representation near the chart when users need precise reference or an accessible alternative.

## Color
Categorical
Token library: --cds-alias-viz-general-

Categorical palettes are used to highlight distinct categories without a specific order.

Primary Colors
1

--cds-alias-viz-general-1
2

--cds-alias-viz-general-2
3

--cds-alias-viz-general-3
4

--cds-alias-viz-general-4
5

--cds-alias-viz-general-5
6

--cds-alias-viz-general-6
7

--cds-alias-viz-general-7
8

--cds-alias-viz-general-8
Additional Colors
9

--cds-alias-viz-general-9
10

--cds-alias-viz-general-10
11

--cds-alias-viz-general-11
12

--cds-alias-viz-general-12
13

--cds-alias-viz-general-13
14

--cds-alias-viz-general-14
15

--cds-alias-viz-general-15
16

--cds-alias-viz-general-16


Best Practices
Limit colors to 8 for optimal readability. If needed, use additional colors from the palette.
Avoid exceeding 16 colors; consider grouping or rethinking visualization design.
Color Application
Colors are ordered from 1 to 16 for optimal contrast.

Accessibility
Utilize 1 px stroke in pie charts or similar instances with clustered colors.
Stroke color should match the background: white for light theme, dark for dark theme.
Sequential
Token library: --cds-alias-viz-sequential-

Sequential palettes are used to show ordered or numerical data, such as progression from low to high.

Blue Palette

--cds-alias-viz-sequential-blue-50

--cds-alias-viz-sequential-blue-100

--cds-alias-viz-sequential-blue-200

--cds-alias-viz-sequential-blue-300

--cds-alias-viz-sequential-blue-400

--cds-alias-viz-sequential-blue-500

--cds-alias-viz-sequential-blue-600

--cds-alias-viz-sequential-blue-700

--cds-alias-viz-sequential-blue-800

--cds-alias-viz-sequential-blue-900

--cds-alias-viz-sequential-blue-1000
Violet Palette

--cds-alias-viz-sequential-violet-50

--cds-alias-viz-sequential-violet-100

--cds-alias-viz-sequential-violet-200

--cds-alias-viz-sequential-violet-300

--cds-alias-viz-sequential-violet-400

--cds-alias-viz-sequential-violet-500

--cds-alias-viz-sequential-violet-600

--cds-alias-viz-sequential-violet-700

--cds-alias-viz-sequential-violet-800

--cds-alias-viz-sequential-violet-900

--cds-alias-viz-sequential-violet-1000
Ochre Palette

--cds-alias-viz-sequential-ochre-50

--cds-alias-viz-sequential-ochre-100

--cds-alias-viz-sequential-ochre-200

--cds-alias-viz-sequential-ochre-300

--cds-alias-viz-sequential-ochre-400

--cds-alias-viz-sequential-ochre-500

--cds-alias-viz-sequential-ochre-600

--cds-alias-viz-sequential-ochre-700

--cds-alias-viz-sequential-ochre-800

--cds-alias-viz-sequential-ochre-900

--cds-alias-viz-sequential-ochre-1000
Aqua Palette

--cds-alias-viz-sequential-aqua-50

--cds-alias-viz-sequential-aqua-100

--cds-alias-viz-sequential-aqua-200

--cds-alias-viz-sequential-aqua-300

--cds-alias-viz-sequential-aqua-400

--cds-alias-viz-sequential-aqua-500

--cds-alias-viz-sequential-aqua-600

--cds-alias-viz-sequential-aqua-700

--cds-alias-viz-sequential-aqua-800

--cds-alias-viz-sequential-aqua-900

--cds-alias-viz-sequential-aqua-1000
Green Palette

--cds-alias-viz-sequential-green-50

--cds-alias-viz-sequential-green-100

--cds-alias-viz-sequential-green-200

--cds-alias-viz-sequential-green-300

--cds-alias-viz-sequential-green-400

--cds-alias-viz-sequential-green-500

--cds-alias-viz-sequential-green-600

--cds-alias-viz-sequential-green-700

--cds-alias-viz-sequential-green-800

--cds-alias-viz-sequential-green-900

--cds-alias-viz-sequential-green-1000
Red Palette

--cds-alias-viz-sequential-red-50

--cds-alias-viz-sequential-red-100

--cds-alias-viz-sequential-red-200

--cds-alias-viz-sequential-red-300

--cds-alias-viz-sequential-red-400

--cds-alias-viz-sequential-red-500

--cds-alias-viz-sequential-red-600

--cds-alias-viz-sequential-red-700

--cds-alias-viz-sequential-red-800

--cds-alias-viz-sequential-red-900

--cds-alias-viz-sequential-red-1000
Examples
Bar Chart
bar chart example
Heatmap
heatmap example
Best Practices
Select palettes that best suit the type of data being visualized.

Color Application
In light themes, higher values are associated with darker colors. In dark themes, the lighter colors represent larger values.

Accessibility
Stroke Contrast
Use --cds-alias-viz-border to ensure stroke usage has adequate contrast against the background. This ensures clear visibility of borders regardless of the data range.

stroke contrast example
Border Color
Utilize 1 px stroke and use --cds-alias-viz-border for the border color at the end of each bar, heatmap, segment, or other elements using sequential palettes.

border color example
Diverging
Token library: --cds-alias-viz-diverging-

Diverging palettes are used to highlight data that has a meaningful midpoint, with values diverging in opposite directions. This is particularly useful for showing data with positive and negative associations, such as profit and loss, temperatures above and below freezing, or performance metrics.

Violet-Aqua Palette

--cds-alias-viz-diverging-violet-aqua-v-700

--cds-alias-viz-diverging-violet-aqua-v-600

--cds-alias-viz-diverging-violet-aqua-v-500

--cds-alias-viz-diverging-violet-aqua-v-400

--cds-alias-viz-diverging-violet-aqua-v-300

--cds-alias-viz-diverging-violet-aqua-v-200

--cds-alias-viz-diverging-violet-aqua-neutral

--cds-alias-viz-diverging-violet-aqua-a-400

--cds-alias-viz-diverging-violet-aqua-a-500

--cds-alias-viz-diverging-violet-aqua-a-600

--cds-alias-viz-diverging-violet-aqua-a-700

--cds-alias-viz-diverging-violet-aqua-a-800

--cds-alias-viz-diverging-violet-aqua-a-900
Blue-Jade Palette

--cds-alias-viz-diverging-blue-jade-b-800

--cds-alias-viz-diverging-blue-jade-b-700

--cds-alias-viz-diverging-blue-jade-b-600

--cds-alias-viz-diverging-blue-jade-b-500

--cds-alias-viz-diverging-blue-jade-b-400

--cds-alias-viz-diverging-blue-jade-b-300

--cds-alias-viz-diverging-blue-jade-neutral

--cds-alias-viz-diverging-blue-jade-j-300

--cds-alias-viz-diverging-blue-jade-j-400

--cds-alias-viz-diverging-blue-jade-j-500

--cds-alias-viz-diverging-blue-jade-j-600

--cds-alias-viz-diverging-blue-jade-j-700

--cds-alias-viz-diverging-blue-jade-j-800
Blue-Green Palette

--cds-alias-viz-diverging-blue-green-b-800

--cds-alias-viz-diverging-blue-green-b-700

--cds-alias-viz-diverging-blue-green-b-600

--cds-alias-viz-diverging-blue-green-b-500

--cds-alias-viz-diverging-blue-green-b-400

--cds-alias-viz-diverging-blue-green-b-300

--cds-alias-viz-diverging-blue-green-neutral

--cds-alias-viz-diverging-blue-green-g-300

--cds-alias-viz-diverging-blue-green-g-400

--cds-alias-viz-diverging-blue-green-g-500

--cds-alias-viz-diverging-blue-green-g-600

--cds-alias-viz-diverging-blue-green-g-700

--cds-alias-viz-diverging-blue-green-g-800
Green-Yellow-Red Palette

--cds-alias-viz-diverging-green-yellow-red-g-700

--cds-alias-viz-diverging-green-yellow-red-g-600

--cds-alias-viz-diverging-green-yellow-red-g-500

--cds-alias-viz-diverging-green-yellow-red-g-400

--cds-alias-viz-diverging-green-yellow-red-g-300

--cds-alias-viz-diverging-green-yellow-red-g-200

--cds-alias-viz-diverging-green-yellow-red-neutral

--cds-alias-viz-diverging-green-yellow-red-r-400

--cds-alias-viz-diverging-green-yellow-red-r-500

--cds-alias-viz-diverging-green-yellow-red-r-600

--cds-alias-viz-diverging-green-yellow-red-r-700

--cds-alias-viz-diverging-green-yellow-red-r-800

--cds-alias-viz-diverging-green-yellow-red-r-900
Examples
Bar Chart
bar chart example
Heatmap
heatmap example
Area Chart
area chart example
Best Practices
Midpoint Clarity: Ensure the midpoint (e.g., zero or average value) is clearly defined in the visualization.
Consistent Scaling: Use a consistent color scale to avoid misinterpretation of data values.
Color Application
Diverging palettes do not differ between light and dark themes.

Accessibility
Stroke Contrast
Use --cds-alias-viz-border to ensure stroke usage has adequate contrast against the background. This ensures clear visibility of borders regardless of the data range.

stroke contrast example
Border Color
Utilize 1 px stroke and use --cds-alias-viz-border for the border color at the end of each bar, heatmap, segment, or other elements using sequential palettes.

border color example
Visualizing Status and Severity
Token library: --cds-alias-viz-severity-

Visualizing status and severity helps users quickly identify and understand the importance or urgency of the data being presented.  These colors can be used in all types of visualizations to convey critical information at a glance. There are two “Free space” tokens - fill and border. Always apply “free-space-fill” together with “free-space-border” to comply with accessibility requirements for contrast.
The standard color states include:


Neutral --cds-alias-viz-severity-neutral - Indicates an inactive, unknown, or neutral status.

Success --cds-alias-viz-severity-success - Indicates a positive or normal status.

Warning --cds-alias-viz-severity-warning - Indicates a cautionary status that requires attention.

Warning-light  --cds-alias-viz-severity-warning-light - Indicates a cautionary status that requires action. In light theme use only with stroke.

Immediate --cds-alias-viz-severity-immediate - Indicates a situation that needs prompt attention.

Critical --cds-alias-viz-severity-critical - Indicates a critical status that requires immediate action.

Free space fill --cds-alias-viz-severity-free-space-fill - To be used as fill for the ‘Free space' in capacity chart

Free space border --cds-alias-viz-severity-free-space-border - To be used as a border for the ‘Free space' in capacity chart
Examples
The unique colors within the severity palette allow it to be combined effectively with any other palettes.

Memory Usage
A dashboard showing available memory.

Success indicates "sufficient memory available"
Warning indicates "moderate memory usage"
Immediate indicates "low memory available"
Critical indicates "critical low memory available"
Free space signifies the free space of the chart.
memory usage example
System Health
Using colors to indicate the health of different systems or components.

Neutral indicates "neutral"
Warning indicates "degraded performance"
Immediate indicates "immediate issue"
Critical indicates "critical failure"
system health example
Incident Reporting
Indicating the severity of reported incidents or issues.

Warning indicates "medium severity"
Immediate indicates "high severity"
Critical indicates "critical severity"
incident reporting example
Best Practices
Consistent Color Usage: Use a consistent color scheme for statuses and severities across all visualizations to avoid confusion.
Limit Color Range: Stick to a strict set of status colors (gray, green, yellow, orange, red) to ensure clarity and avoid overwhelming users.
Accessibility
Stroke Contrast
Use strokes when there are clusters of different colors to enhance visibility and differentiation.
Example: In pie charts or similar visualizations, apply a stroke that matches the background color - white for light themes and dark for dark themes.
stroke contrast example
Alternative Indicators
such as labels or icons to reinforce the meaning of colors

### Accessibility
Content
Use Patterns and Textures
Use High Contrast Colors
Avoid Information Overload
Provide Clear Labels
Interactive Elements
Alternative Format
Testing and Validation
Ensuring that your data visualizations are accessible is crucial for inclusivity. Here you can find some guidelines and best practices.

Use Patterns and Textures
Color blindness affects a significant portion of the population, making it difficult for these individuals to distinguish between certain colors. By incorporating patterns and textures, you can ensure that your visualizations are accessible to everyone, regardless of their ability to perceive color.

Application
Apply patterns or textures to different data points in charts to differentiate between categories, series, or data sets.

Dual Encoding
Use both color and pattern to encode information. This ensures that even if color perception is impaired, the patterns can still convey the necessary distinctions.

Examples
example of using both color and textures to convey information
Do
Textures, Shapes and Line Styles
Use textures to ensure differentiation between segments, explore the use of different line styles and shapes.
example of an accessibility violation by using only color to convey information
Don't
Don't Rely Solely on Color
Avoid using color as the only means of conveying information.
Use High Contrast Colors
Choose color combinations with high contrast to make distinctions more apparent. Avoid color pairs that are problematic for color blind users, such as red-green or blue-purple. Use palettes like --cds-alias-viz-general-, --cds-alias-viz-sequential-, --cds-alias-viz-diverging-, and --cds-alias-viz-severity- for better distinction and the suggested border token to ensure clear visibility of borders regardless of the data range.

Examples
example of a passing color contrast test
Do
Check Contrast
Ensure different segments meet the contrast requirements of 3:1 ratio with the background. Use Clarity palettes in the provided order, as colors are ordered for optimal contrast and tested for different types of color blindness.
example of a stroke contrast
Do
Stroke Contrast
Use the provided chart border tokens to ensure stroke usage has adequate contrast against the background.
example of a failing color contrast test
Don't
Don't Use Problematic Color Pairs
Avoid colors that do not meet contrast requirements, and combinations that are difficult for color blind users to distinguish, such as red-green or blue-purple.
Avoid Information Overload
example of using an "other" slice in a pie chart to limit the number of colors
Do
Limit Colors
Limit colors to 8 for optimal readability; avoid exceeding 16 colors.
example of using too many colors in a pie chart
Don't
Don't Overload with Colors
Limit the number of colors used in a single visualization to avoid overwhelming users and ensure clarity.
Provide Clear Labels
Ensure that all data points, lines, and areas are clearly labeled. This reduces the reliance on color alone to interpret the data.

Examples
example of a chart label
Add direct labels to bars, lines, and segments.

example of a chart label
Use callouts or annotations to highlight key data points.

Interactive Elements
For digital visualizations, incorporate interactive elements that allow users to hover over or click on data points to get more information.

Examples
example of an interactive chart tooltip
Tooltips that display detailed data values.

example of an interactive chart legend
Interactive legends that highlight corresponding data on the chart.

Alternative Format
Provide data in alternative formats such as a downloadable file or a table. This enables users to review data in their preferred format.

Testing and Validation
Simulators and Tools: Use color blindness simulators and accessibility testing tools to check how your visualizations appear to users with different types of color blindness.

Examples: Online tools like Coblis (Color Blindness Simulator) or built-in accessibility features in design software such as Stark for Figma.