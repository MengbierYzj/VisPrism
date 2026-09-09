# The Urban Institute

Source: https://urbaninstitute.github.io/graphics-styleguide/


## chart Typography and Sizing
Good chart typography creates a hierarchy among elements and guides the reader through the visual. Urban uses a defined set of font sizes and styles to create this hierarchy.

Urban uses the Lato font for all our products, including the website, PDF publications, and presentations. A suitable replacement is the default Arial font. If Lato is not installed on your computer, contact the Tech and Data department.

The font sizes in Urban charts depend on whether the chart is produced for the web or within a PDF. The Excel macro and R theme apply the correct font sizes to both web and PDF figures.

Descriptive text — title, subtitle, sources, notes, and logo — are handled differently for web and print (PDF) products. For web products, all text is included in a single image (e.g., PNG) file. For print (PDF) products, descriptive text is placed directly in the Microsoft Word file and not the chart image. Data labels, axis labels, and other text used directly in the chart should be included in the chart image.

Font

Color

Case

PDF figures

Web figures

Figure number

Lato Regular

#0A4B69 or RGB(10,75,105)

ALL CAPS

8pt

11px

Title

Lato Black

#000000 or RGB(0,0,0)

Title (all major words capitalized)

12pt [inserted in the Word document, not the actual chart]

20px

Subtitle

Lato Italic

Black (#000000 or RGB(0,0,0))

Sentence (only the first word capitalized)

10pt [inserted in the Word document, not the actual chart]

16px

Axis titles

Lato Regular

Black (#000000 or RGB(0,0,0))

Sentence

8.5pt

12px

Axis labels

Lato Regular

Black (#000000 or RGB(0,0,0))

Sentence

8.5pt

12px

Data labels

Lato Regular

Black (#000000 or RGB(0,0,0))

Sentence

8.5pt

12px

Legend text

Lato Regular

Black (#000000 or RGB(0,0,0))

Sentence

9.5pt

14px

Source

Lato Regular

Black (#000000 or RGB(0,0,0))

Sentence

8pt

11px

Notes

Lato Regular

Black (#000000 or RGB(0,0,0))

Sentence

8pt

11px

Most of Urban’s charts will be full width (760px for web and 6.25” for PDFs). The main content width on the Urban website is 760px, which translates to approximately 125.83 characters in Excel. In PDF products, simple figures can be 3.13” wide, which is half the width of full-size figures.

^ table of contents



## anatomy
Key elements of Urban charts are as follows:

The chart should be referenced in the text.
Titles use headline/title case, and subtitles use sentence case; all titles are left aligned.
All text within the figure uses sentence-style capitalization.
In all Urban products, researchers should reference charts and tables in the text to provide context for the data. Figures and tables should be placed immediately after the paragraph that references them. If the chart consists of a limited number of values, consider a couple sentences of text to explain the data in lieu of an image.

Urban charts require a title, source line, and axis or other labels identifying the elements and units of the chart. This can be achieved by using some combination of a subtitle, axis titles, axis labels, data labels, and legend (not all elements will be necessary for every figure). Urban charts posted on the web also include an Urban tagline/logo in the lower-right corner of the figure so that when others copy and paste our charts, Urban is identified as the source.

For Excel charts produced for the web, add the title, subtitle, source, and notes directly in the Excel chart. Because Excel’s chart title and subtitle fields are limiting in terms of formatting, we use a regular text box for all the text at the top of the graphic, as well as for the source and notes text at the bottom.

In charts produced for PDF publications, add the title, subtitle, sources, and notes as text directly in the Microsoft Word file. Axis titles, labels, and the legend are added in Excel or in the R chart space directly.

On the web
Detailed image of a graph showing all the text sizes, type, size, color, and position of all text in an online graph from the Urban Institute.
In print (for PDFs)
Detailed image of a graph showing all the text sizes, type, size, color, and position of all text in a PDF graph from the Urban Institute.
The chart parts are described in detail below.

Titles: Use headline case for titles and sentence case for subtitles. Keep them short and simple. Try to explain the chart in a few words and draw conclusions where possible. Use a subtitle to add qualifiers or further clarification. The unit of measurement should be mentioned only once, either in the subtitle or the y-axis label. For example, instead of a purely descriptive title, such as “Labor Force Participation Rate, Men and Women, 1950–2024,” a more active title would be “The Labor Force Participation Rate Has Declined for Men and Increased for Women.” Subtitles can be used to denote specifics about the data, such as time periods, frequency, units, or geography.
Axis titles and labels: Use sentence-style capitalization for all text within the figure, including axis titles, data labels, and legends. In sentence-style capitalization, the first letter of the sentence and any proper names (including program names) are capitalized, and all other text is set in lowercase. For example, “Percentage of total funding,” “2021 operating expenses,” “Denver Regional Transportation District,” and “$50,000 and above.” You can use abbreviations in the axis titles and labels as long as the abbreviations are defined in the notes.
Source: The source line should contain the source of the data for the figure and include full publication information, including the authors, title, and publication date, all in Urban’s notes citation style. All figures in Urban publications should have a source line. If the source of the data is Urban analysis, the source line can read “Authors’ analysis.”
Notes: The notes line can include technical information about methodology, statistical explanations, and notes that apply to certain values. The notes should also define all acronyms and abbreviations used within the figure, using this format: “FPL = federal poverty level.” Notes that apply to certain cells in tables should use superscript letters as note references. Asterisks should only be used to indicate significance levels (e.g., p < 0.001, * = significant at 0.001 level).
Legend: Stretch legends across the top of the chart between the title/subtitle and y-axis label. Order the series in the legend in a logical way, mirroring the order of the data in the chart. When possible, directly label the data in the chart and omit the legend.
Data labels: Chart elements can be labeled to provide readers with the specific data values or additional context. Data labels should match the units of the chart and be placed as close as possible to the actual data point (e.g., top or inside a bar on a bar chart or a point on a line chart). Explanatory labels should be concise and explain important, surprising, or interesting aspects of the graph.
Tagline: The Urban tagline is built from standard text using Lato Bold, 9pt, black, small caps, with 0.5pt of expanded character spacing. The word “Urban” is colored blue (RGB[22,150,210] or #1696d2) and “Institute” is black (RGB[0,0,0] or #000000). The Excel add-in automatically includes the tagline for web graphs. For PDF products, the tagline is added as text in the Microsoft Word file at the bottom right of the figure, with no spacing between the figure and the tagline. The tagline is omitted in government-funded products.
^ table of contents

## Color
Urban's main colors are cyan, gray, and black. Yellow and magenta are used as secondary colors throughout the new Urban brand. In general, yellow and magenta should be used sparingly; these colors are best for highlighting purposes, such as when drawing attention to a certain category or indicating a trend line. Tertiary colors for graphics include space gray, green, and red, and should be used infrequently.

When selecting colors for charts and graphs, first consider the type of data you are presenting. Usually, data for visualizations can be grouped into one of four main groups: categorical, sequential, diverging, or binary (see next sections for examples in the Urban color palette).

Categorical palettes are best to distinguish discrete chunks of data that do not have an inherent ordering (e.g., race, state of residence).
Sequential palettes are appropriate when data follow a certain order, such as when data range from low to high (e.g., poverty rates, unemployment rates). The typical approach is to use light(er) colors for low(er) values and dark(er) colors for high(er) values.
Diverging palettes are used to distinguish values that vary from a central value, such as the average, median, or zero. Diverging palettes will use a neutral color for the central value, such as white or gray, and then employ a sequential color palette in either direction. For example, a sequential palette for changes in per capita gross domestic product might be centered at zero with a white color, then range to dark yellow for negative values and to dark blue for positive values. The center of the diverging palette should always be labeled to avoid confusing the reader.
Binary palettes are a subset of categorical palettes and are used to distinguish between two distinct groups, such as Republicans and Democrats. When comparing data on binary gender groups, do not use blue to represent men and pink to represent women. Instead, choose a color combination such as yellow and cyan or another combination of our main graphic colors.
For more information about the subtleties of color and choosing colors for your data visualizations, refer to Datawrapper's blog post "A detailed guide to colors in data vis style guides” and Nightingale magazine's blog posts on the subject.

Color combinations
Urban’s core color palette consists of eight main colors, ordered below in a hierarchy from core colors to less commonly used colors. All Urban tool sets, including the Excel add-in and color palette, and the urbnthemes R package, follow this hierarchy.

Specific shades of each main categorical color are found below for use in graphs that require sequential and diverging palettes. It should be noted that tints and shades of colors in the Excel add-in and color palette do not exactly match these colors.

The palettes below offers multiple options for combining colors in Urban charts, though only the combinations shown in the first set of each section are included in the Excel add-in and R theme. When in doubt, individuals are encouraged to consult the Urban Design and/or Data Visualization teams for assistance in choosing color combinations.

Main graphic colors
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #d2d2d2
rgb(210,210,210)
CMYK: 0,0,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Hex: #ec008b
rgb(236,0,139)
CMYK: 0,100,41,7
Hex: #55b748
rgb(85,183,72)
CMYK: 54,0,61,28
Hex: #5c5859
rgb(92,88,89)
CMYK: 0,4,3,64
Hex: #db2b27
rgb(219,43,39)
CMYK: 0,80,82,14

Text and contrast
Urban Institute data visualizations should strive to meet Web Content Accessibility Guidelines (WCAG) to make web content most accessible to people with disabilities. (Read more about those international standards here and in the Urban Institute report Do No Harm Guide: Centering Accessibility in Data Visualization). Urban follows WCAG 2.0 Level AA guidance to ensure that background color and text pairings maximize contrast.

The color palettes below contain the correct white or black text to pass the WCAG AA ratings for contrast at smaller text sizes (18px or less).

Shades of main colors
Hex: #cfe8f3
rgb(207,232,243)
CMYK: 15,5,0,5
Hex: #a2d4ec
rgb(162,212,236)
CMYK: 31,10,0,7
Hex: #73bfe2
rgb(115,191,226)
CMYK: 49,15,0,11
Hex: #46abdb
rgb(70,171,219)
CMYK: 68,22,0,14
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #12719e
rgb(18,113,158)
CMYK: 89,28,0,38
Hex: #0a4c6a
rgb(10,76,106)
CMYK: 91,28,0,58
Hex: #062635
rgb(6,38,53)
CMYK: 89,28,0,79
var colors=["#CFE8F3","#A2D4EC","#73BFE2","#46ABDB","#1696D2","#12719E","#0A4C6A","#062635"];

Hex: #f5f5f5
rgb(245,245,245)
CMYK: 0,0,0,4
Hex: #ececec
rgb(236,236,236)
CMYK: 0,0,0,7
Hex: #e3e3e3
rgb(227,227,227)
CMYK: 0,0,0,11
Hex: #dcdbdb
rgb(220,219,219)
CMYK: 0,0,0,14
Hex: #d2d2d2
rgb(210,210,210)
CMYK: 0,0,0,18
Hex: #9d9d9d
rgb(157,157,157)
CMYK: 0,0,0,38
Hex: #696969
rgb(105,105,105)
CMYK: 0,0,0,59
Hex: #353535
rgb(53,53,53)
CMYK: 0,0,0,79
var colors=["#F5F5F5","#ECECEC","#E3E3E3","#DCDBDB","#D2D2D2","#9D9D9D","#696969","#353535"];

Hex: #fff2cf
rgb(255,242,207)
CMYK: 0,5,19,0
Hex: #fce39e
rgb(252,227,158)
CMYK: 0,10,37,1
Hex: #fdd870
rgb(253,216,112)
CMYK: 0,15,56,1
Hex: #fccb41
rgb(252,203,65)
CMYK: 0,19,74,1
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Hex: #e88e2d
rgb(232,142,45)
CMYK: 0,39,81,9
Hex: #ca5800
rgb(202,88,0)
CMYK: 0,56,100,21
Hex: #843215
rgb(132,50,21)
CMYK: 0,62,84,48
var colors=["#FFF2CF","#FCE39E","#FDD870","#FCCB41","#FDBF11","#E88E2D","#CA5800","#843215"];

Hex: #f5cbdf
rgb(245,203,223)
CMYK: 0,17,9,4
Hex: #eb99c2
rgb(235,153,194)
CMYK: 0,35,17,8
Hex: #e46aa7
rgb(228,106,167)
CMYK: 0,54,27,11
Hex: #e54096
rgb(229,64,150)
CMYK: 0,72,34,10
Hex: #ec008b
rgb(236,0,139)
CMYK: 0,100,41,7
Hex: #af1f6b
rgb(175,31,107)
CMYK: 0,82,39,31
Hex: #761548
rgb(118,21,72)
CMYK: 0,82,39,54
Hex: #351123
rgb(53,17,35)
CMYK: 0,68,34,79
var colors=["#F5CBDF","#EB99C2","#E46AA7","#E54096","#EC008B","#AF1F6B","#761548","#351123"];

Hex: #dcedd9
rgb(220,237,217)
CMYK: 7,0,8,7
Hex: #bcdeb4
rgb(188,222,180)
CMYK: 15,0,19,13
Hex: #98cf90
rgb(152,207,144)
CMYK: 27,0,30,19
Hex: #78c26d
rgb(120,194,109)
CMYK: 38,0,44,24
Hex: #55b748
rgb(85,183,72)
CMYK: 54,0,61,28
Hex: #408941
rgb(64,137,65)
CMYK: 53,0,53,46
Hex: #2c5c2d
rgb(44,92,45)
CMYK: 52,0,51,64
Hex: #1a2e19
rgb(26,46,25)
CMYK: 43,0,46,82
var colors=["#DCEDD9","#BCDEB4","#98CF90","#78C26D","#55B748","#408941","#2C5C2D","#1A2E19"];

Hex: #d5d5d4
rgb(213,213,212)
CMYK: 0,0,0,16
Hex: #adabac
rgb(173,171,172)
CMYK: 0,1,1,32
Hex: #848081
rgb(132,128,129)
CMYK: 0,3,2,48
Hex: #5c5859
rgb(92,88,89)
CMYK: 0,4,3,64
Hex: #332d2f
rgb(51,45,47)
CMYK: 0,12,8,80
Hex: #262223
rgb(38,34,35)
CMYK: 0,11,8,85
Hex: #1a1717
rgb(26,23,23)
CMYK: 0,12,12,90
Hex: #0e0c0d
rgb(14,12,13)
CMYK: 0,14,7,95
var colors=["#D5D5D4","#ADABAC","#848081","#5C5859","#332D2F","#262223","#1A1717","#0E0C0D"];

Hex: #f8d5d4
rgb(248,213,212)
CMYK: 0,14,15,3
Hex: #f1aaa9
rgb(241,170,169)
CMYK: 0,29,30,5
Hex: #e9807d
rgb(233,128,125)
CMYK: 0,45,46,9
Hex: #e25552
rgb(226,85,82)
CMYK: 0,62,64,11
Hex: #db2b27
rgb(219,43,39)
CMYK: 0,80,82,14
Hex: #a4201d
rgb(164,32,29)
CMYK: 0,80,82,36
Hex: #6e1614
rgb(110,22,20)
CMYK: 0,80,82,57
Hex: #370b0a
rgb(55,11,10)
CMYK: 0,80,82,78
var colors=["#F8D5D4","#F1AAA9","#E9807D","#E25552","#DB2B27","#A4201D","#6E1614","#370B0A"];


One group
For one color group, grey should not be used as it loses focus while magenta draws attention

Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100

Two groups
Categorical
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #d2d2d2
rgb(210,210,210)
CMYK: 0,0,0,18
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Use blue and red sparingly, usually only when comparing political data.

Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #db2b27
rgb(219,43,39)
CMYK: 0,80,82,14
Sequential
Hex: #a2d4ec
rgb(162,212,236)
CMYK: 31,10,0,7
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18

Three groups
Categorical
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #d2d2d2
rgb(210,210,210)
CMYK: 0,0,0,18
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #55b748
rgb(85,183,72)
CMYK: 54,0,61,28
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #ec008b
rgb(236,0,139)
CMYK: 0,100,41,7
Sequential
Hex: #a2d4ec
rgb(162,212,236)
CMYK: 31,10,0,7
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #0a4c6a
rgb(10,76,106)
CMYK: 91,28,0,58

Four groups
Categorical
Use yellow and magenta sparingly, usually only for highlighting data.

Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #d2d2d2
rgb(210,210,210)
CMYK: 0,0,0,18
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #d2d2d2
rgb(210,210,210)
CMYK: 0,0,0,18
Hex: #ec008b
rgb(236,0,139)
CMYK: 0,100,41,7
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Hex: #55b748
rgb(85,183,72)
CMYK: 54,0,61,28
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #000000
rgb(0,0,0)
CMYK: 0,0,0,100
Hex: #fdbf11
rgb(253,191,17)
CMYK: 0,25,93,1
Hex: #ec008b
rgb(236,0,139)
CMYK: 0,100,41,7
Sequential
Hex: #cfe8f3
rgb(207,232,243)
CMYK: 15,5,0,5
Hex: #73bfe2
rgb(115,191,226)
CMYK: 49,15,0,11
Hex: #1696d2
rgb(22,150,210)
CMYK: 90,29,0,18
Hex: #0a4c6a
rgb(10,76,106)
CMYK: 91,28,0,58