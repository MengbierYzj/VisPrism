IBM
type:technology corp
Design principle:
- Understandable: An IBM data visualization should communicate a message at a glance, in a clear, concise and easy-to-understand way. Avoid elements that make a visualization appear complex, distant or disjointed. You can achieve this effect using established typographic and visual communication principles that enhance the form, readability and meaning. You should remove anything gratuitous and avoid ambiguity or unnecessary embellishments that distract the user from the main concept. Less is more.
- Essential: Design is an exercise in decision-making. When you design data visualization, you must consider the utility in answering a question or solving a problem. A deﬁnite structure, contrast, rhythm and hierarchy of the information displayed is essential to guide users through complex information. Choose the visual model that best conveys the message. Take a dive into our Charts section to get a better understanding of how to pair your data with the most effective chart type.
- Impactful: As IBMers, we love celebrating the beauty and creativity of things, but we also invest in showing how things work, conveying concepts and displaying details. Our data visualization should always enable the user to reach the goal and explore the topic in detail by using a clear system of ﬁlters, functions and well-known interaction patterns that make the affordance unmistakable. We embrace a love for details and multiple layers of information as part of a good design practice.
- Consistent: Just as the core values of IBM have remained consistent over the years, similarly, we want our visualizations to be consistent both stylistically and from a data point of view. Be a good storyteller. Ensure each visual representation corresponds to the relative numerical quantity, and pay attention to the proportions and scale of the elements to keep the integrity of the data. A misrepresentation of data could lead to a misinterpretation of reality. 
- Contextual: Successful systems require both ﬁxed and fluid elements of expression. The innovative ways in which we use these elements deliver distinction and uniqueness, but the context should be the primary driver of our decisions. A visualization should be crafted based on the environment of the audience and its constraints. If it’s for marketing or analysis purposes, what’s the level of familiarity with the subject matter, and does the ﬁnal result respect the time required by the audience being asked to experience it? These examples are just a few of the essential aspects in a data visualization that affect layout and style, the level of complexity, and the amount of detail revealed.
Chart:
Charts are typically divided into categories based on their goals, aesthetics or visual features. Since charts can be versatile and used in different ways, details and features of these categories are explained and contextualized here. Use these best practices as you create data visualizations.
- Comparisons:
  - Charts designed for comparison aim to visualize differences between elements. Most of the time comparisons rely on the ability of the human eye to identify longer or bigger shapes with very little or no effort. Side-by-side positioning and alignment of the visual elements make comparisons even easier. These charts are used for time-based data, for example, units sold per day or worked hours per month. They are also used for categorized data, for example, revenue by market or sold units by team.
  - Recommend chart: Simple bar、Grouped bar、Floating bar、Lollipop、Bubble、Radar、Wordcloud
- Trends:
  - Trend charts represent data along with the time dimension. Use them mainly to track changes over periods of time of varying duration and scale. They rely on direction to show the evolution of consecutive values and might be influenced by different cultural contexts. These charts are used for time-based data, for example, revenue by quarter or rainfall per day.
  - Recommend chart: Line、Area、Boxplot、Histogram、Stream
- Part to whole:
  - The goal of these charts is to show the inner subdivision of a value among different categories or groups. Mostly used to represent percentages, they can also be used for absolute values. Their function does not depend on the graphic shapes used, such as pie, donut, square and so on. These charts are used for categorized data, for example, subdivision of revenue by product or percentage of users by browser.
  - Recommend chart: Donut、Pie、Stacked bar、Bullet、Stacked area、Meter、Gauge、Tree map、Circle pack
- Correlations:
  - These charts are better suited to highlight the possible correlation between two or more indicators and how they might affect each other. Correlation charts have the final goal of making it easier for the human eye to spot combined behaviors. These charts are used for multidimensional data, for example, correlation between phone-call duration and customer satisfaction.
  - Recommend chart: Scattorplot、Heatmap、Parallel coordinates
- Relationships and connections：
  - Charts included in this category represent hierarchies. The intent is to explain the role of an element within an ecosystem or to observe the inner nature of a subject in different phases and states of a process. These charts are used for categorized data, for example, country of origin of asylum seeker and gender. They are also used for multidimensional data, for example, number of active users by testing phase.
  - Recommend chart: Alluvial diagram、Network diagram、Tree diagram
- Maps:
  - Maps are the easiest and most immediate way to communicate geolocated information. Maps allow the user to recognize areas and places, to understand the geographical context of the topic and to identify patterns, all relying on the position of elements. These charts are used for geographical data, for example, voters by county or average wage by neighborhood.
  - Recommend chart:Chorpleth map、Propotional symbol、Connecting lines.
Design:
- Chart anatomy
  - Title, labels and legend: The title should reflect the main insight the data reveals. The legend should explain the chart’s meaning by defining the association of each visual property, such as color, shape and size, to the corresponding data. When possible, use labels directly on the chart to avoid long legends. All the text should be concise and easy to understand. Use concise title, don't use long and too descriptive title
  - Axes, ticks and grid: Axes, ticks and the grid should help the reader understand the proportions and scale of the data, the indicators involved and their unit of measure. Avoid filling the chart frame with too many elements, as it impacts the user’s ability to interpret the data. Use the correct density of grid lines and labels. Don’t use too many elements or the chart will be difficult to read.
- Legend:
  - Usage:When possible, avoid using a legend and label data representations directly. Legends rely on visual association, which can make a chart more difficult to understand.Your chart doesn’t need a legend if it only presents one data category. Only use a legend if you can’t safely assume there will be enough space to apply labels directly. Use clear language and avoid acronyms in legends. This also applies to titles and axis labels. For example, Remove legends to simplify the chart when only one data category is needed or only one color is used. In-chart labels are ideal for charts with predictable data and ample empty space.
  - Position: The legends are positioned at the bottom of a chart by default.
    - Bottom (default) and top:Position the legend at the bottom or top of a chart in situations where space is scarce, such as a dashboard.
    - Left:Position the legend to the left of the chart when better type alignment is needed. Be sure the surrounding elements of the chart are not too closely clustered.
    - Right:Position the legend to the right of the chart when space is plentiful, or when you would like to provide the maximum context. In mobile, the legend could revert to a stack
    - Overlay (geospatial only):In geospatial charts, legends can be overlaid on top of a graph frame as long as the legend has a background opacity of 80% of the chart’s background color. Since geospatial charts can vary drastically in appearance, the legend can be placed on either side of the chart, top- or bottom-aligned, whatever best accommodates the content. To demonstrate the legend’s background opacity, we chose to place the legend at the top left in the chart below. See the Master data visualization design file for more detail about geospatial legends.
      
- Axes and labels: Axes and labels provide critical context for the information within a chart. Use simple, easy-to-understand descriptors and metrics to label your chart and axes.
  - Starting at zero:
    - When starting at non-zero is bad: Always start numerical axes at zero for part-to-whole and comparisons charts, such as bar and area chart. Truncating the Y axis can distort the perception, making a small difference look big and significant. For example, For bar charts, the numerical axis should start at zero.When an axis starts at non-zero, percentage differences between bars are exaggerated.
    - When starting at non-zero is good:Line charts and scatter plots are less sensitive to this distortion because they are intended to communicate trends and not the relative size of the difference. In these cases, cropping the Y axis helps users more easily identify the direction of change. For example, For line charts showing stock market activities, the existence of peaks and valleys in trends is more important than the true size of the change.
  - Breaks in axes
    - Sometimes it is useful to skip part of the axis to bring data on the extreme ends into view without distortion. When the axis contains a break, use a sinusoidal line to replace the straight axis line.
    - On the X axis, the break can be fluid with graph area size, with a minimum width of 16px. On the Y axis, we recommend using a fixed distance of 16px for the break.
    - If data is available during an axis break, re-style line segments to use 0.5px stroke and hide circles representing data points.
  - Time series:
    - Consistent increments: Never change axis ticks increments to accommodate data availability. If any form of axis compression is required, use the provided axis break styling to visually denote the compression.
    - Localization:In time series, X-axis labels reflect the time increment in the data. When possible, use localized date and time format, or user preference. Otherwise, the chart defaults to the format presented below.
    - Landmark labels:Whenever data crosses into a new time cycle, such as a new day, month, or year, semibold the label to make it a “landmark” label to provide additional context for the labels following it.
  
- Color: The application of the IBM color palette brings a unified and recognizable consistency to the array of digital products and interfaces. This color pallette applies to data visualization, as well, but isn’t restricted to appearance only; it decreases recognition times, conveys meaning and helps users make faster, more informed decisions. When designing IBM’s data visualization, be sure to maximize accessibility and harmony, but also keep an eye on cultural and psychological contexts.
  - Emphasize the story you want to tell: Color is one of the most powerful sensory cues and a highly influential visual property. Create a sharp contrast between elements to focus the user’s attention on the meaning of the chart, but be essential—every color should have a reason for being there. Conversely, even the absence of color delivers information. Shades of grey ensure data points are visible while not distracting from the key insights. On the other hand, connecting specific colors to certain key metrics helps your audience easily recognize frequent indicators.
  - Improve readability and hierarchy of elements:Caring about contrast means caring if users will be able to read your chart on their screens, even in low light and if you use shades of colors like light grey. Well-chosen colors reduce the time for viewers to gain insights and help them understand the message sooner. Rely on categorical palettes if you want to maximize contrast between data that doesn’t have an inherent relationship, while sequential palettes are good to show relationships or hierarchies between data. Reinforce color meaning with other strong visual features, like shape, line or pattern, to make the focal point immediately recognizable.
  - Represent quantity: Color can convey meaning. By illuminating a chart through sequential or diverging palettes, you add depth and dimension to specific data, drawing attention to the quantitative aspect of the story.
  - Texture and markers:Visualizations can be rich and “colorful,” even in situations when color can’t be used. IBM employs different shades of black, together with patterns and markers, as a valid substitute for color. Patterns aren’t just a decoration, but become a way to convey information. Use lines with different weights and play with the density of elements.
  - 
  - color palette: 
    - Categorical palettes:Categorical (or qualitative) palettes are best when you want to distinguish discrete categories of data that do not have an inherent correlation.The colors of this palette should be applied in sequence strictly as described below. The sequence is carefully curated to maximize contrast between neighboring colors to help with visual differentiation.
      - Light mode:
        1. Purple 706929c4
        2. Cyan 501192e8
        3. Teal 70005d5d
        4. Magenta 709f1853
        5. Red 50fa4d56
        6. Red 90570408
        7. Green 60198038
        8. Blue 80002d9c
        9. Magenta 50ee538b
        10. Yellow 50b28600
        11. Teal 50009d9a
        12. Cyan 90012749
        13. Orange 708a3800
        14. Purple 50a56eff
      - Dark mode:
        1. Purple 608a3ffc
        2. Cyan 4033b1ff
        3. Teal 60007d79
        4. Magenta 40ff7eb6
        5. Red 50fa4d56
        6. Red 10fff1f1
        7. Green 306fdc8c
        8. Blue 504589ff
        9. Magenta 60d12771
        10. Yellow 40d2a106
        11. Teal 4008bdba
        12. Cyan 20bae6ff
        13. Orange 60ba4e00
        14. Purple 30d4bbff
    - Sequential palettes
      - Monochromatic: The monochromatic palettes are good for relationship charts and trend charts. In light themes, the darkest color denotes the largest values. In dark themes, the lightest color denotes the largest values.
        - Discrete mode:
          - Option 1
            - Blue 10edf5ff
            - Blue 20d0e2ff
            - Blue 30a6c8ff
            - Blue 4078a9ff
            - Blue 504589ff
            - Blue 600f62fe
            - Blue 700043ce
            - Blue 80002d9c
            - Blue 90001d6c
            - Blue 100001141
          - Option 2
            - Purple 10f6f2ff
            - Purple 20e8daff
            - Purple 30d4bbff
            - Purple 40be95ff
            - Purple 50a56eff
            - Purple 608a3ffc
            - Purple 706929c4
            - Purple 80491d8b
            - Purple 9031135e
            - Purple 1001c0f30
          - Option 3
            - Cyan 10e5f6ff
            - Cyan 20bae6ff
            - Cyan 3082cfff
            - Cyan 4033b1ff
            - Cyan 501192e8
            - Cyan 600072c3
            - Cyan 7000539a
            - Cyan 80003a6d
            - Cyan 90012749
            - Cyan 1001c0f30
          - Option 4
            - Teal 10d9fbfb
            - Teal 209ef0f0
            - Teal 303ddbd9
            - Teal 4008bdba
            - Teal 50009d9a
            - Teal 60007d79
            - Teal 70005d5d
            - Teal 80004144
            - Teal 90022b30
            - Teal 100081a1c
        - Continuous mode:
          - Option 1
            - Blue 10edf5ff
            - Blue 20d0e2ff
            - Blue 30a6c8ff
            - Blue 4078a9ff
            - Blue 504589ff
            - Blue 600f62fe
            - Blue 700043ce
            - Blue 80002d9c
            - Blue 90001d6c
            - Blue 100001141
          - Option 2
            - Purple 10f6f2ff
            - Purple 20e8daff
            - Purple 30d4bbff
            - Purple 40be95ff
            - Purple 50a56eff
            - Purple 608a3ffc
            - Purple 706929c4
            - Purple 80491d8b
            - Purple 9031135e
            - Purple 1001c0f30
          - Option 3
            - Cyan 10e5f6ff
            - Cyan 20bae6ff
            - Cyan 3082cfff
            - Cyan 4033b1ff
            - Cyan 501192e8
            - Cyan 600072c3
            - Cyan 7000539a
            - Cyan 80003a6d
            - Cyan 90012749
            - Cyan 1001c0f30
          - Option 4
            - Teal 10d9fbfb
            - Teal 209ef0f0
            - Teal 303ddbd9
            - Teal 4008bdba
            - Teal 50009d9a
            - Teal 60007d79
            - Teal 70005d5d
            - Teal 80004144
            - Teal 90022b30
            - Teal 100081a1c
    - Diverging palettes:Please note that diverging palettes do not differentiate between light and dark themes.
      - Palette 1:The red-cyan palette has a natural association with temperature. Use this palette for data representing hot-vs-cold.
        - Red 80750e13
        - Red 70a2191f
        - Red 60da1e28
        - Red 50fa4d56
        - Red 40ff8389
        - Red 30ffb3b8
        - Red 20ffd7d9
        - Red 10fff1f1
        - Cyan 10e5f6ff
        - Cyan 20bae6ff
        - Cyan 3082cfff
        - Cyan 4033b1ff
        - Cyan 501192e8
        - Cyan 600072c3
        - Cyan 7000539a
        - Cyan 80003a6d
      - Palette 2:The purple-teal palette is good for data with no temperature associations, such as performance, sales, and rates of change.
        - Purple 80491d8b
        - Purple 706929c4
        - Purple 608a3ffc
        - Purple 50a56eff
        - Purple 40be95ff
        - Purple 30d4bbff
        - Purple 20e8daff
        - Purple 10f6f2ff
        - Teal 10d9fbfb
        - Teal 209ef0f0
        - Teal 303ddbd9
        - Teal 4008bdba
        - Teal 50009d9a
        - Teal 60007d79
        - Teal 70005d5d
        - Teal 80004144
      - Alert palette: Alert colors are used to reflect status. Typically, red represents danger or error; orange represents a serious warning; yellow represents a regular warning, and green represents normal or success.
        1. Red 60da1e28
        2. Orange 40ff832b
        3. Yellow 30f1c21b
        4. Green 60198038
      - Gradient use:Gradients are good for highlighting extremes in a range of values. Use a gradient on single category visualizations only if needed. Multiple gradients are often inaccessible and are discouraged in our system. Gradients should not be used to represent any meaningful progression or divergence. Never use a gradient in place of a sequential palette.
    - Color and texture:Chart legends use color as the default distinguishing property for data sets and values. Texture can be used instead of, or in addition to, color to make your chart accessible for users with visual impairment. For example: Texture can improve accessibility. See the accessibility page for all approved textures.