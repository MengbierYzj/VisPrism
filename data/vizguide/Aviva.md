# Aviva

Source: https://standards.aviva.com/framework/element-library/components/pie-chart/


## Visualization Guide Content


### Pie charts

Use pie charts to visually display an animated percentage amount

#### Design and usage

Use pie charts to visually display:

- Multiple segments - to present up to 5 segments of numerical information;

- Highlighted segments - to show 100% of a pot and further information about each segment.

##### Shared rules

The pie variations carry these rules:

- Structure:When a chart is revealed for the first time within the viewport it will animate clockwise its data set completing the pie circle.

- Accessibility and screen readers: To ensure the component meets accessibility standards, the component must have a 3px divider between each of the pie segments.


- Placement: The pie chart and key must sit within the grid, with the block consuming six columns of the grid if the key is placed to the right of the pie chart.

Two pie charts with keys can sit side by side on the full 12 column grid.

Pie charts should only be used on white backgrounds.

#### Multi-segment pie chart

Structure:
- All multi-segment pie charts must be accompanied by a legend (key); this contains the labels and values for the segments of the pie chart.

- The chart legend (key) can be placed to the right or beneath the chart.

- The chart can show a minimum of 2 and a maximum of 5 segments.

- Each of the five potential segments will have a specific colour which must always be placed in the same order:

Segment 1: #1a61bd

Segment 2: #a9b2c6

Segment 3: #5a8ccc

Segment 4: #c2c8d5

Segment 5: #7988a9

- Other atoms can be placed within the key lock-up, including:

A title

A total (if numerical values)

A primary or secondary call to action or a text-link

A block of copy

Labels

- The legend (key) will contain the labels for each of the segments in the pie chart.

- The colours in the legend (key) label must match the appropriate segments in the pie chart.

- Accessibility and screen readers

To ensure the component meets accessibility standards, the component must have a legend (key) with labels.

Placement

If needed, up to three pie charts can be placed side by side; in this instance the keys will be placed below the charts.

Use case and exception scenarios

To display percentage or numerical data to customers, such as pension values or investments with 2-5 segments of data.

For charts with only 1 segment and/or to use alternative accent colours; see

doughnut charts

.

Pie charts with highlighted segments

Follows the same rules as a multi-segment chart except:

The first chart shown is the full data set you wish to use.

Each following chart refers to a single highlighted section of the first chart.

Labels

The full multi-segment chart shows a legend (key) for all segments of the data set.

Highlighted charts only show a legend (key) for that single highlighted section.

Use case and exception scenarios

Use two or more multi-segmented charts with highlights to explain individual sections from one multi-segment card carrying the complete data set.


### doughnut charts
Use doughnut charts to visually display:

- A single animated segment - showing an animated numeric figure, like a percentage amount;
- Multiple segments - to present up to 5 segments of numerical information;
- Highlighted segments - to show 100% of a pot and further information about each segment.

### Shared rules
All three doughnut variations carry these rules:

Structure
- When a chart is revealed for the first time within the viewport it will animate clockwise its data set completing the doughnut circle.

Accessibility and screen readers
- To ensure the component meets accessibility standards, the component must have a 3px divider between each of the doughnut segments.

Placement
- The doughnut chart and key must sit within the grid, with the block consuming six columns of the grid if the key is placed to the right of the doughnut.
- Two doughnut charts with keys can sit side by side on the full 12 column grid.
- Doughnut charts should only be used on white backgrounds.
- Do not use a multi-segment doughnut (with a legend (key) to the right or beneath) in the same section as a single segment doughnut.