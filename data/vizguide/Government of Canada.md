# Government of Canada

Source: https://design.gccollab.ca/data/data-overview/


## principle

Data visualizations should aim to represent and answer one question. The goal is to provide a brief overview of the data, and tell a visual story that makes sense to the user. Graphs should be used to visually represent datasets in ways that tables cannot. If the data is easy to understand without a visualization, usually the simplest option (a table) is best.

- Simplicity A general rule for data visualizations is to keep the visual elements as simple as possible. Only necessary information such as labels, values, and bars or lines should be present. A key or legend should be provided for more complex data that may have multiple colours or types of information. Colours and other visual elements should always be kept to a minimum when possible.

Visuals should only enhance the data, and should never distract. Best practices include eliminating backgrounds, lightening grids, and reducing the number of colours used in a graph.

If one graph is too complex to represent a certain dataset, the data should be represented in multiple, simple graphs.

- Multiple Formats

When you use data visualizations, it is recommended to represent the data in multiple formats where possible. Regardless of the type of visualization you use, a simple data table, or other ways of viewing the raw data, should be available somewhere on the page. This allows users to view and analyze the data in a way that makes the most sense to them, as well as easily identify individual data points.

## Labels

### Graph Titles

Graph and table titles in this design system use the typography style for heading 2.

Titles should be as short as possible, and accurately reflect the question the dataset is trying to represent. Titles always use title-case capitalization.

### Axis Labelling

Both the x and y-axes should always be labeled. Labels should be placed outside of the data area. Labels should use simple and clear language, and accurately represent the data being shown. Axis labels use the typographic style for heading 4.

For quantitative labels, the unit of measurement should be included in the label.

### Data Increments

Qualitative data values should be labelled in a logical way, such as consecutive months. For quantitative values, they should be labelled using round numbers or decimals that fit the data range. Always include an additional increment greater than the dataset.

In some visualizations with many axis points, skipping labels is an effective way to reduce visual clutter. Axis ticks should be separated with sufficient space to clearly read each label. Intervals between labels should always be consistent.

On the x-axis, value labels should be centered to their corresponding tick mark. For y-axis labels, they should be left-aligned and kept above the y-axis lines. Long text labels should be rotated 45 degrees around an origin directly below their corresponding axis tick.

### Data Formats and Abbreviations

When possible, labels and values should avoid abbreviations unless it is a conventional data format. If spacing is a concern, it is recommended to skip labels in a way that makes sense for the data.

Some data formats should always use abbreviations:

Common Abbreviations

Unit

Abbreviations

Days of the week

Mon, Tues, Wed, Thurs, Fri, Sat, Sun

Months

Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec

12-hour time

1 a.m., 2 p.m., 12 p.m. etc.

Standard money abbreviations

$1.2k, $3.4m, $6.2b, etc.

### Colours and Textures

Graphs and visualizations should always aim to use as little colour as possible. If multiple colours are required, they should be a complimentary palette that are both distinguishable when placed in close proximity. Colour choice should avoid bias (e.g. red and green) unless specifically related to the data. Any colour is acceptable for a visualization so long as it meets contrast requirements.

For increased accessibility, it is also recommended to use textures in addition to colour differences, so that variables are easier to distinguish.

See specific types of visualizations for use of colour. In general, each variable should have one designated colour, and only graphs showing multiple variables should have multiple colours.

Axis lines should use light grey (#E0E0E0), to not distract from other colours used in the visualization

For more information about colour choice, visit the colour section.

## color
Colour
Primary Colour Palettes
Primary colour palettes are the main colours used on your application. These colours are used on all major components that make up your application including buttons, badges, progress indicators etc. You want the use of these colours to be consistent across your application. For example, all primary buttons in an application should use the same hue.

A primary colour palette typically includes 2-3 main colour swatches, with varying shades of these swatches (lighter and darker) to allow for flexibility when building your application. These additional shades can be created by changing the saturation level or brightness of the main colour swatch. See the Aurora Borealis section below for an example of a full colour palette.

For Government of Canada applications it is required that all colours meet the WCAG AA accessibility level for contrast, though AAA is ideal. You can use online contrast checkers to ensure that the colours you choose meet accessibility standards when combined with text.

Once chosen, you can apply your own colours simply by modifying the hex codes in your CSS for various elements.

Swatch Families
Swatch families consist of an array of colours that are used consistently within your particular application. Swatch families include a set of hues that work well together and that can be combined to create a full colour palette.These colours are used to add variety and visual appeal to the main components of your application.

To build a full colour palette, choose 2-3 colour swatches as your base. From there, these hues can be modified to provide lighter or darker shades, gradients, and other variants. Combined with standard alert colours, light and dark themes, and text colours, all of these hues create a full colour palette to be used in an application.

Below are some sample swatch families:

Aurora Borealis
The main colour swatches used for the Government of Canada's Open and Accessible Digital Workspace (GCTools).

#002D42
#137991
#6DD2DA
#15A3A6
#92CC6F
Canada.ca Theme
The official hues for Canada.ca web pages and other external-facing applications. Provides lots of neutrals, and a signature blue and red used for accents , headers and footers.

#333000
#26374A
#AF3C43
#F5F5F5
#FFFFFF
Thunder and Lightning
Optional swatch family. Neutrals with a signature yellow for a small pop of colour.

#002D42
#4D5D6C
#96A8B2
#CECECE
#FEC04F
Blue Complimentary
Optional swatch family that uses a complimentary colour scheme. Blue is used to convey trust, while orange and yellow provides a small splash of colour to applications.

#0D467D
#137991
#6DD2DA
#FF9F40
#FEC04F
Triad
Optional swatch family. A versatile set of colours that provides lots of options for a colourful but sophisticated application.

#7E0C33
#024571
#5DC1BE
#F6CF22
#EDDB7C
Green and Blue
Optional swatch family. A bright cool-toned colour palette that provides a fresh look for web applications.

#0278A4
#4E4741
#83C3F2
#C9DF61
#C1D699
Secondary or Complementary swatches
Secondary colour swatches are completely optional and may provide designers with additional colours to play with on an application. These secondary swatches are often used in small quantities to draw attention to key pieces on web pages and for visual diversity and aesthetic purposes.

These colours should only be applied to visual elements that enhance the appearance of the page. They should never be used on elements which communicate information visually, either for task completion or the structure of the page.

If you choose to include secondary colour swatches to your application, here are some places where you can use these additional colours:

Logos or Icons
Images
Graphics
Other elements used for visual enhancements
Basic Interface Colours
Black Text
Text in this design system is displayed in an off-black colour. Black text can be used on any light background (see: Light Theme) or any button or element that uses a light colour. When adding text to any background that is not black it is essential to check the contrast for accessibility. Significant contrast between the background/element colour and the text ensures readability, even for those with visual impairments such as colour blindness.

Please see Typography for more information about using text colour.

#252525



White Text
Light text in this design system is displayed in an off-white colour. White text can be used on any dark background (see: Dark Theme) or any button or element that uses a dark or light colour.

When adding white text it is essential to check the contrast for accessibility. Significant contrast between the background/element colour and the text ensures readability, even for those with visual impairments such as colour blindness.

Please see Typography for more information about using text colour.

#FFFFFF



Muted Text
Muted text is used for secondary text elements such as captions, placeholder text and timestamps. This muted text colour only works on light backgrounds (see: Light Theme) or light-coloured elements. For dark backgrounds or bright/dark elements, use white text.

Please see Typography for more information about using text colour.

#666666



Light Theme
By default, most applications will follow the light theme. This theme includes various shades of white for different background/foreground levels. For the majority of applications #FAFAFA is a good shade to use as a background colour, with white (#FFFFFF) as the container or card colour.

#CCCCCC
#F5F5F5
#FAFAFA
#FFFFFF



Dark Theme
Some applications may wish to also incorporate a dark theme. This theme includes various shades of black and grey for different background/foreground levels.

#000000
#212121
#303030
#424242



Error Colours
Error colours are used to indicate system failures and malfunctions.You should use colours users associate with the level of severity. Do not reuse the specific shade for error colours anywhere else on the application.

#923534
#D3080C
#F3E9E8



Warning Colours
Warning colours are used for notices that require the user’s acknowledgement.

#66512C
#FF9900
#F9F4D4



Success Colours
Success colours are used when confirming that the user’s input was successful.

#2B542C
#278400
#D8EECA



Info Colours
Info colours are used when providing additional information and notes to the user.

#245269
#269ABC
#D7FAFF



Colours Used in Aurora
Elements in this system use a clean and colourful swatch family that communicates the brand and the values of the Open and Accessible Digital Workspace.

Our colour swatches include a mix of blue and green hues that communicate trust but adds a colourful pop to our collaboration and productivity applications.

The primary swatch family used in this system is titled Aurora Borealis and uses the following hex codes:

#002D42
#137991
#6DD2DA
#15A3A6
#92CC6F
Full Palette
Using the above swatches, Aurora Borealis was developed into a full colour palette to use in applications. This palette includes a lighter variants of the base hue, darker variants, and gradient samples. Below are also some examples of palette variations being used on an application header.

#002D42
#175573
#4285A6
#82BDD9
#CCEFFF
#F3F8FA
#137991
#3993A8
#6BB2C2
#8ECDDB
#B5E7F2
#F7FEFF
#6DD2DA
#87DAE0
#A1E1E6
#B2E9ED
#C2EFF2
#F7FEFF
#15A3A6
#41BCBF
#77D6D9
#B6F0F2
#E6FEFF
#F7FFFF
#92CC6F
#9FD47F
#B2DB99
#C7E3B5
#DFEDD5
#FAFFF7
Gradient Examples




CSS
Gradient 1
background: rgb(11,65,77);
background: linear-gradient(76deg, rgba(11,65,77,1) 2%, rgba(19,121,145,1) 40%, rgba(247,254,255,1) 100%);

Gradient 2
background: rgb(19,121,145);
background: linear-gradient(90deg, rgba(19,121,145,1) 0%, rgba(21,163,166,1) 55%, rgba(109,210,218,1) 100%);

Gradient 3
background: rgb(0,166,154);
background: linear-gradient(90deg, rgba(0,166,154,1) 0%, rgba(105,217,163,1) 100%);

Gradient 4
background: rgb(19,121,145);
background: linear-gradient(90deg, rgba(19,121,145,1) 0%, rgba(21,163,166,1) 40%, rgba(146,204,111,1) 100%);
Creative Accent Colours
Since the Open and Accessible Digital Workspace is a full suite of tools, multiple secondary swatches may be used across the workspace to add visual diversity to particular applications. Within our team, we have an unwritten rule that the lead designer on each application is responsible for choosing one accent hue that can be used for fun visual elements within that application.

This accent colour is used for aesthetic elements only, and major UI elements still follow the Aurora Borealis swatch family.


## Typography
Fonts
Aurora uses two font families for all digital products: Rubik and Nunito Sans. Both Rubik and Nunito Sans are open source fonts and can be downloaded from Google Fonts for free.

Rubik is used for titles and headings, while Nunito Sans is used for sub-headings, buttons and paragraph text.

If only system fonts are available, use Calibri or another similar sans-serif typeface as a replacement. Use similar sizing and weight as shown below, with small adjustments as needed.
Font Choice
Both fonts chosen for this design system enhance accessibility and readability. Sans-serif fonts have a simpler structure than serif and script fonts, so users with reading disabilities or visual impairments are able to more easily decipher characters.

If you choose to use fonts other than the ones listed here, it is recommended that your digital product use sans-serif rather than serif or script fonts.

Some systems may not be able to download or display the fonts in this design system. This can be for a variety of reasons including firewall restrictions, accessibility settings, etc. In this case your application should be set to use the browser's default font.

About the Typefaces
Rubik is a sans-serif font designed by Philipp Hubert and Sebastian Fischer for the Chrome Cube Lab project. With 5 different weights, Rubik works well as a paragraph or display font. Rubik is popular internationally and is used in more than 180,000 websites.

Nunito Sans is part of Google's super family typefaces. It was created by Vernon Adams and improved by Jacques Le Bailly to include a full set of weights. This font is popular all over the world and is used by 50,000 websites.

Titles (H1)
Titles appear only on the top of pages and indicate high-level navigation points.

Titles are displayed using Rubik Light at 36 points in the colour #252525 on a light background or #FFFFFF on a dark background.

Headings (H2-H6)
There are five different sub-headings. All sub-headings use the colours #252525 on a light background or #FFFFFF on a dark background.

The headers use the following typographic styles:

Heading 2: Rubik Regular at 28 points (1.75 em).

Heading 3: Rubik Medium at 24 points (1.5 em) with a tracking modifier set to 10.

Heading 4: Rubik Regular at 21 points (1.3125 em).

Heading 5: Nunito Sans Regular at 18 points (1.125 em).

Heading 6: Nunito Sans Bold at 16 points (1em).

Heading 2
Heading 3
Heading 4
Heading 5
Heading 6
Paragraph Text
Paragraph text is used for most text content found on the application. Paragraph text is set to Nunito Sans Regular at 16 points (1em) with a leading of 24 points. Unless indicating a hyperlink or navigation point, paragraph text should not have added emphasis.

Paragraph text uses the colours #252525 on a light background or #FFFFFF on a dark background.

Line-Breaking
The Aurora design system is consistent with the following best practices for line-breaks:

• Avoid hyphenation at the end of a line.

• Avoid leaving gaps or orphans hanging on a line.

• Avoid overly large indentation.

Line Length
The ideal length for body text is around 40-60 characters. If line length is too short or too long it has a negative impact on readability. Our design system follows these guidelines and aims for approximately 60 characters per line.

Pull Quotes
Pull Quotes are used to indicate key phrases from the content displayed on the page (i.e. in articles or blogs). Pull quotes are integrated into paragraphs.

Pull quotes are indented by 50px with a vertical line in the application's secondary colour. The line is 4px wide. Padding between the line and the text is 8px. The text is displayed using Nunito Sans Regular at 1.25 em, with a line height of 200%.

See Colour for more information on choosing accessible colours for your pull quote lines.

" What an awesome pull quote! "

<p style="border-left-width: 4px; border-left-style: solid; border-left-color: #0ba7b4; padding-left: 8px; font-size: 1.25em; line-height: 200%;"> " What an awesome pull quote! "</p>
Lists
There are three different types of lists:

Un-ordered lists: These lists use bullet points to indicate groups of content. The default bullet is an open circle with an outline in the primary colour. An indented bullet includes an open circle with a grey outline.

Item 1
Item 2
Item 3
Ordered lists: Ordered lists use numbers to indicate content that requires a hierarchy.

Item 1
Item 2
Item 3
Interactive lists: Interactive lists include content that is clickable. These lists include a hover and click state, and act as minor navigation points.

Item 1
Item 2
Item 3
Hyperlinks
Link text is used within paragraphs to indicate hyperlinks and navigation points. Hyperlinks and navigation points use Nunitio Sans Regular at 16 points with a leading of 24 points.

It is recommended that the link text be underlined and displayed in a secondary colour used in the application. It is also recommended that hyperlinks do not exceed one line in length, and are applied to 2-4 key words rather than a full sentence or line.

Visited links should be indicated by a different colour. Typically, a best practice for visited links is to use a muted version of your hyperlink colour, a secondary colour, or the standard purple: #551A8B.

Emphasis
For accessibility purposes, colour cannot be the sole source of emphasis. Be sure to add emphasis to text by making the font bold and increasing the contrast.

Typographic formatting such as italics or underlining should be used sparingly and only when they genuinely enhance communication with all readers.