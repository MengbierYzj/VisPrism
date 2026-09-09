# Baltimore City Data Fellows Project

Source: https://storymaps.arcgis.com/stories/d19f7d4d2a9b49c7b8f68730e3cda1e6  


## Scope and stance

The Baltimore City Data Viz Style Guide is a springboard rather than a prescriptive manual. It asks designers to develop charts, dashboards, and tables with the audience and application in mind. The guide emphasizes clarity, accessibility, consistency, effectiveness, user-centered design, and iterative testing.

## Principles

- **Clarity:** Many applications make it easy to create charts and graphs, but design is often overlooked leading to misinterpretation and confusion even when the underlying information is the product of a sophisticated, well-thought-out process.
- **Accessibility:** People speak a variety of languages, are in different environments, and have a range of abilities. Strong visual communicators make decisions about how text, images, and charts are designed, so that everyone has an equal opportunity to process information. 
As content creators, it’s important to recognize section  508 of the Rehabilitation Act of 1973  which was amended in 1998 to require government agencies to make their electronic and information technology (EIT) accessible to people with disabilities. 

- **Consistency:** Continuity builds trust and credibility. By using one set of guidelines, people will associate visuals designed with these guidelines and build a relationship with City of Baltimore analysts as a whole. 
- **Effectiveness:** The time you spend collecting and analyzing data is only time well spent if your visualizations are able to effectively communicate the trends and insights you discover.  



## Typography and color

- Use typographic hierarchy to establish reading order. Roboto and Roboto Condensed are used in examples; system fonts such as Arial are recommended for web publication when the font is not guaranteed to be installed.
- Prefer fewer colors: grayscale, monochromatic, or sequential palettes are the default starting points. Use desaturated colors, test palettes with a color-vision simulator, and test with multiple users.
- Use color to highlight important information or communicate meaningful categories. Titles, axis titles, and labels should be black; data points may be grayscale or color. Do not let adjacent colors disappear into each other or the background.

## Chart guidance

### Line charts (fever lines)

- Use for continuous data and trends over time, including accelerations, decelerations, peaks, and troughs.
- Choose minimum and maximum values for the y axis so that the fever line takes up about two-thirds of the entire range. If this setting gets the baseline near zero, then best practice is to set the baseline to zero. 
- Plotting multiple fever lines on the same chart can provide clues about how two trends differ or resemble one another. This is only useful with a small number of lines, however, so avoid making “spaghetti” plots with more than five fever lines. 



### Bar charts

- Bar charts  should be used when you are showing segments of information. Vertical bar charts are useful to compare different categorical or discrete variables, such as agencies, age groups, communities, etc., as long as there are not too many categories to compare. They are also very useful for time series data.
- Form and shading. Don’t add shadows behind bars or use three-dimensional vertical bars. These additions do not contain data and only distract from important information. 

- Let the bar stand on its own. The width of the bars should be about twice the width of the space between the bars. All the bars in a single chart should be the same color and shade since they measure the same variable.

- Projections, estimates, and negative numbers. A lighter-shaded bar can be used to distinguish projections and estimates from actual values. A gray background can be used to identify the negative zone of a bar chart.

- The Y axis always starts at zero. A bar chart that doesn’t begin at a zero baseline is misleading. Truncation obscures the discrete total value of each bar and makes comparison of the data difficult. 

- Avoid axes labels that are turned on a 45 or 90 degree angle and choose a horizontal bar instead.  

- Choose a single color for all of the bars or highlighting one or two purposefully. 

- Horizontal bars are great for comparing counts or another single metric for categories because the categories are easily read to bottom, especially when the category names are long (as opposed to having them rotated to fit in a vertical arrangement).
Horizonal bar graphs are often most effective when the data are sorted from highest to lowest—this enables quick comparison among groups and identification of outliers or clusters.

If the categories are meant to sum to 100%, a 100% stacked bar chart might be better to show each category’s proportion of the whole. (A treemap is another option here.)

### Treemaps

-  Tree maps  are generally used to show percentage or proportional data and usually the percentage represented by each category is provided insid the corresponding category. If you're not sure if your data is best for a tree map, use a bar chart to be safe. Tree maps are preferred over pie and donut charts. 
- Place the largest block of the tree map at the top left. Because people tend to read tree maps clockwise, it's most effective to put the largest block at the top left, then disperse rest of data from the left to the right so the smallest blocks are on the right.

Combine categories to display six to ten categories. Tree maps are useful when the reader can clearly discern the proportion of parts to the whole. When there are too many blocks, it becomes too difficult to gain any information from a tree map visual. 

Do not use tree maps to display relationships between categories. A tree map can only be used if the sum of the individual parts add up to a meaningful whole, and is built for visualizing how each part contributes to that whole. If the goal is to compare the categories, a bar chart would be more useful.



### Scatter plots

- Use  scatter plots  when you want to show the correlation or relationship between two variables.
- Count the right thing. It's easy to connect two variables and see how they interact, but understanding what you're visualizing the correlation of is important. The chart on the left is essentially measuring the number of hot days where the chart on the right shows the number of violent crimes committed per temperature divided by the number of days that temperature occured, allowing us to show the correlation between violent crime and temperature. 

- Remove outliers. Use a max value for the x and y axis that removes outliers and highlights the trend in the data.

- Regression Line. Add a regression line to show the relationship between the two variables.

- P-value. Add a p-value and explain the significance with an annotation.

- Simple is better. Show only one group per graph. If you need to show more than one grouping, display them in two separate graphs unless the chart is meant to show relationships through clustering.

- Simple is better. Show only one group per graph. If you need to show more than one grouping, display them in two separate graphs unless the chart is meant to show relationships through clustering.






### Tables
Table
Only use tables if it helps eliminate confusion, is helpful for looking up or comparing specific values, or to communicate more than one unit of measure. 

Organization. Data should be categorized by underlying structure (agency, location, rank). If used for looking up data, categories should be listed in alphabetical order if there is not a natural order. Columns should be listed in logical order on how they are calculated (Column A + Column B = Column C).

Style. Numbers should be right-justified, text should be left-justified. 

Unhelpful vs. Optimal Visual Guides. Busy gridlines or alternating gray rows distract the reader from the data. In a small table, the eyes can easily follow the numbers across a table. Instead use thin gridlines every three to five entries to help the reader follow numbers across a table. A two or three column table does not require any guides. Shading can be used to highlight a column of data or an entry. 

Charts in Tables. Whenever space is available in a table, it is always helpful to chart the column of data that is the main message. 

## Text elements

Annotations 

- Along with a well-defined hierarchy, annotations can assist with delivering information to readers. They are especially useful for individuals with vision impairments, but everyone benefits from them. Annotations can be used to summarize the main takeaway of a chart. They should be limited if the chart is static, but multiple annotations can be added if they are interactive. 

