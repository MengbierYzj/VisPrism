# World Health Organization

Source: https://data.who.int/about/datadot/data-design-language


## philosophy

Clear
Data presentations are tailored to information needs, understandable and approachable.

Transparent
They reveal uncertainty, precision, provenance, and coverage of the data.

Open
We create rich data experiences for everyone, through accessible, international, adaptable, and participatory approaches to data visualization.

Robust
Data can be consumed in a variety of channels and sizes, through robust and lean technological solutions.

## anatomy
### Colors
Building on the WHO color palette, we developed a set of beautiful, and expressive color themes with corresponding scales.

Color themes
For all themes, brand, foreground, background and text colors are provided in varying strengths, to meet different background contrast requirements.

All colors are defined separately for dark and light environments. The dark theme can be used in low-light conditions or to highlight particular sections of a page, e.g. a hero chart.

brand/base
#008dc9
WHO brand color.
brand/stronger
#0f2d5b
WHO brand color with stronger contrast
brand/weaker
#90d3fb
WHO brand color with weaker contrast


Category colors
The colors for nominal data are based on the WHO 2021 brand colors. They were adapted to make them perceptually suitable for data visualization and fully accessible.

Specifically, the category colors fulfill the following requirements:

Colorblind-safe, tested for the most common types of color vision.
Nameable, to be distinguishable and easy to refer to verbally.
Equally salient, with comparable brightness and saturation.
Sufficient background contrast on both light and dark backgrounds: To fit colors to different sizes of text and visual marks, all colors come in various strengths for different background contrasts.

category/base/0
#f4a81d
Used for nominal data of category 0.
category/base/1
#f26829
Used for nominal data of category 1.
category/base/2
#bd53bd
Used for nominal data of category 2.
category/base/3
#6363c0
Used for nominal data of category 3.
category/base/4
#008dc9
Used for nominal data of category 4.
category/base/5
#40bf73
Used for nominal data of category 5.
category/base/99
#cccccc
Used for nominal data in the "other" category.

sequential scales:
#d7e6f3
#75b6d6
#0582bb
#0f2d5b

Diverging scales
Diverging scales can be used for quantitiative data that contains both positive and negative values. Depending on use case, it can be more appropriate to place zero at the center of the scale, or to the median. Like sequential scales, diverging color scales are interpolated in LAB space between defined stops.

Diverging scales fulfill the following criteria:

Blend over a neutral color — close to the background — in the center.
Perceptually uniform increase in saturation and decrease in lightness towards both ends of the scale (inverse for dark backgrounds).
Colorblind-safe tested for the most common types of color vision.
Sufficient lightness range, to make values easy to read.
Versions for dark backgrounds with inverted brightness contrast.

### Typography
Our charts use a fixed set of sizes, ranging from xxl (for large numbers) over m(for normal text) to s (for captions and axes labels).

Fonts and styles
Google's Noto Sans is the primary typeface used. The Noto font collection presents highly readable and friendly typefaces for a wide variety of languages, is open source and free to use.

Sizes
The typograhic system features a concise vocabulary of font sizes, in three different variants: bigger size differences (54px to 14px) in large charts, and smaller ones on medium (38px to 14px) and small charts (28px to 12px).

### layout
Spacing
Likewise, spacing variables vary with size as well. There are eight levels of spacing, coming in three different chart size variations.

### Symbology
We use a defined vocabulary of shapes, textures, icons to represent specific data properties.
Projected Values
Projected values are indicated through hatching for filled areas and dashed lines. These styles can either be explained in a legend or through direct labeling. Data labels for projected values are shown in italics.

Uncertainty
For values with uncertainty, an area with lower opacity is drawn between upper & lower bound. Upper & lower bound are indicated through thinner lines. The mean is shown in the same ways as for reported/estimated values. In text, uncertainty is indicated in square brackets.

Example of a chart with projected values and uncertainty
Data gaps
Data gaps should be labeled in charts using the same symbols. The symbols are be explained in legend.
### Chart anatomy

Our charts follow a compositional logic: functional elements and visual layers can be reused and encountered across chart types.

Chart container
Chart containers wrap a single chart and offer slots for external elements (e.g. text elements, controls, legends etc). Like charts, containers come in three size sets, depending on their width. Depending on context, different styling options and themes are available. In chart compositions, multiple chart containers are combined, for instance in grid arrangements.
Title and subtitle, source
The chart container supplies information on indicator displayed, the selected geographical units and time range (usually in the subtitle), the indicator unit, and in external contexts, the source for citation purposes. If needed, a caption for further explanatory text can be added as well.

Axes
Axes components are used for orientation in cartesian coordinate systems. We supply 3-6 ticks per axis maximum. If there are more available values than ticks, round numbers should be used. Default gridlines are dotted, the zero baseline has a heavy, solid line style. In right-to-left languages, the x-axis is flipped.
Legends
Charts with visual encodings such as color, shape, texture, etc. require a legend to explain the value mapping. We differentiate sequential, categorical, and diverging scales for color encoding, as well as line or mark rendering properties (solid, dotted, …) for value status types (estimated, reported, …). Legends follow the reading direction: in right-to-left languages, the higher end should be placed to the left.
Selection markers
Charts can have selected entities. Selection state can be supplied by the author of a visualization, or the user. Selected items are supplied with data labels, and have a consistent, clearly distinct look. In case the number of selected items exceeds a certain threshold (typically 2-3), non-selected items will be rendered in a uniform, low contrast color, in order to facilitate focussing on the selected items.
Data labels
Explicit, inline value annotation is supplied in all charts. Our charts support auto-annotations (rule-driven hints about data extension, extremes, and data point of interest), inspection labels (as a result of mouseover, tap, or keyboard focus actions for quick data inspection) as well as locked-in, permanent labels (resulting from explicit user- or author-driven selection actions).
Reference marks
Authors can choose to add reference marks (points, lines, areas) to charts. Those are tied to specific data values and can contain a label as well as graphic symbols. Some chart types also offer the option to add data series as reference, such as the global average over time.