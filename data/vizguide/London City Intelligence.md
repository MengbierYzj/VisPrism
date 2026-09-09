# London City Intelligence

Source: https://data.london.gov.uk/blog/city-intelligence-data-design-guidelines/


## principle
Remove the noise, highlight the signal

## design
### Practical steps to reduce clutter
Minimal gridlines & tick marks
Use as few gridlines and ticks as is 
necessary to understand the range 
& context of your data. Aiming for 
around 5 gridlines / tick marks is 
usually adequate. Make your 
gridlines as light as possible, but still 
visible.
Remove borders
Remove borders around the chart to 
give it more space.
Minimise labelling
Labelling your axis as unobtrusively 
as possible, gives you space to 
accentuate important points on the 
axis or in the data.
Remove decoration and effects
Get rid of any unnecessary key lines 
around shapes, drop shadows and 
bevelling effects.
Don’t try and show too much
If you have lots of data to show, 
perhaps use small multiples of 
charts rather than over complicating 
one chart. 
Minimise use of colour
Remove colour encoding of data 
that is there only for context or 
comparison. Using lighter/thinner 
grey lines for this contextual data 
allows to better highlight with 
meaningful colour later.

### Practical steps to highlight the data or message
Focus
Focus ranges to show data most 
clearly. Only if doing so doesn’t 
remove important context. 
Use colour or line weight
Highlight the important data with 
a consistent / thematic colour, 
and increasing the weight of the 
line 
Label directly
This can help draw attention to a 
key data point and simplifies 
reading by not having to translate 
the meaning of a colour legend.
Show key points on the axis
Highlight key dates or values on the 
axis. Consider only including the 
date ticks on your axis that are 
relevant to the chart.
Highlight important thresholds 
and contextual ranges
Draw attention to important 
thresholds in the range of your data. 
E.g. placing a stronger gridline when 
your y-axis DOES start at zero. Or 
where you need to show data 



### layout
design & readability
Maintain consistency
Make consistent design decisions throughout your work, and certainly 
within any given presentation. For example, once your reader has learned 
that “pink” might mean “London” don’t contradict that in your next chart.
Aid navigation & context
Allow users to navigate your presentation or document easily by 
signposting (with colour or icons) where they are. This also gives them 
context for the data they are reading.
Consider chart comparison
Ensure any two charts that are likely to be compared, use the same space 
for layout and use the same scale on the x & y axis.
Consistent text hierarchy across charts and within document
Your chart should feel that it belongs to your document, so keep the text 
size consistent with the hierarchy of your document or web page.

Consistent layout, labels & lines
For ease of comprehension, it’s important that your charts are presented 
consistently, and are as clean and uncluttered as possible.


## color
The Mayor of London brand guildlines contain this set of 11 colours, of 
which Pink (#ee266d) is the hero colour. These colours are brilliantly 
impactful for brand communications when used in isolation or small 
pairings. However for data visualisation and information design we need to 
think about colour slightly differently

When presenting data, and while not ideal, we sometimes need to use a 
wide range of categorical colours. These categorical colours, for the sake of 
clarity and accessibility need to be visually distinct from each other.
Some of the brand colours, can’t be used to together in a visualisation 
because they are not visually distinct enough for some readers, and in some 
environments and applications (like small lines or points).
This subset of the brand colours do work as categorical colours:
A: Pink
B: Cyan
C: Dark Pink
D: Mustard
E: Red
"#ee266d",
"#00aeef",
"#9e0059",
"#dca000",
"#e0001b"
rgb(238,38,109);
rgb(0,174,239);
rgb(158,0,89);
rgb(220,160,0);
rgb(224,0,27);
These colours and pairings are problematic for accessibility:
Green vs Red
Blue vs Purple and Dark Pink
Purple vs Dark Pink
Orange vs Red


While fewer colours are better, we often need numerous categorical colours 
on charts and maps. The following colours have been carefully chosen to 
work with LDN Pink and Dark Pink and (unless coloured areas are small) are 
discernable by people with most* colour vision deficiancies.
Below are suggested default usage order and possible colour ramps.
Core categorical colours by default use order
A: Blue
B: LDN Dk Pink
C: Yellow
D: Red
E: Green*
F: Purple
G: Turquoise
H: Pink
I: Orange
J: LDN Pink*
"#6da7de",
"#9e0059",
"#dee000",
"#d82222",
"#5ea15d",
"#943fa6",
"#63c5b5",
"#ff38ba",
"#eb861e",
"#ee266d"
rgb(109,167,222);
rgb(158,0,89);
rgb(222,224,0);
rgb(216,34,34);
rgb(94,161,93);
rgb(148,63,166);
rgb(99,197,181);
rgb(255,56,186);
rgb(235,134,30);
rgb(238,38,109);