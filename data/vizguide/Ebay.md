Ebay

## Philosophy
- Keep it simple
Progressive disclosure is key—ensure you are using data visualization as a tool to aid in understanding, not to overwhelm users with too much information all at once.
- Tell a story
Focus on what you want to communicate and who you’re communicating to. Understanding data is much easier when there is a human narrative. Think about how you would tell the story in a sentence.
- Scale thoughtfully
Our charts scale seamlessly for all screen sizes and users. Use designated colors, interactive states, and scaling behaviors to ensure they are simple and accessible in all contexts.

## anatomy
### Title
Required. Titles name the data being visualized. Use exacting language.
- Use sentence case
- No ending punctuation
- Aim for 1-2 words

### Subtitle
Optional. Use a subtitle when the title alone isn’t enough to understand the chart. Add context that the title is missing. Don’t restate the title.
- Use sentence case
- No ending punctuation
- Aim for 1-2 lines

### Primary metric
Optional. Use when one number is the main takeaway and the chart exists to support it. Don't use when there’s multiple equally important values.
- Use sentence case
- No ending punctuation
- For money, see formatting numerals

### Axis
The X and Y axes help users compare data points consistently across graphs. Choose intervals that avoid overcrowding. For example, if the chart covers a full year of daily data, don't display all 365 days on the X-axis. 
Axis labels
Leave at least 16px between labels and include key anchor points. Start the Y-axis at 0 for accurate proportions, and mark significant time points on the X-axis, like financial quarters or days of the week.
- Use sentence case
- No ending punctuation
- 
### Tooltips
Tooltips reveal precise data values when users hover over or interact with the chart, letting them explore specific data points. The title of the tooltip names the date or time the datapoint is from.
- Use sentence case
- No ending punctuation

Learn more about writing tooltips.

### Color
Data viz color tokens
All of the colors we use in our data visualization patterns have been vetted for accessibility and fit into three categories: trends, charts, and line graphs. You can find the colors we use throughout this page in Color Tokens.
Foreground
Title        Value on light        Value on dark
color.foreground.primary        color.core.neutral.800        color.core.neutral.200
color.foreground.secondary        color.core.neutral.600        color.core.neutral.500
color.foreground.disabled        color.core.neutral.400        color.core.neutral.600
color.foreground.accent        color.core.blue.500        color.core.blue.400
color.foreground.attention        color.core.red.600        color.core.red.400
color.foreground.warning        color.core.yellow.550        color.core.yellow.400
color.foreground.success        color.core.kiwi.600        color.core.kiwi.400
color.foreground.onAccent        color.core.neutral.100        color.core.neutral.800
color.foreground.onAttention        color.core.neutral.100        color.core.neutral.800
color.foreground.onSuccess        color.core.neutral.100        color.core.neutral.800
color.foreground.onInverse        color.core.neutral.100        color.core.neutral.800
color.foreground.onStrong        color.core.neutral.100        color.core.neutral.800
color.foreground.onDisabled        color.core.neutral.100        color.core.neutral.800
color.foreground.onWarning        color.core.neutral.800        color.core.neutral.800
color.foreground.link.visited        color.core.pink.600        color.core.pink.400
color.foreground.link.legal        color.core.blue.650        color.core.blue.400
color.foreground.link.primary        color.foreground.primary        color.foreground.primary
Border
Title        Value on light        Value on dark
color.border.strong        color.core.neutral.700        color.core.neutral.100
color.border.medium        color.core.neutral.500        color.core.neutral.600
color.border.subtle        color.core.neutral.300        color.core.neutral.700
color.border.accent        color.core.blue.500        color.core.blue.400
color.border.attention        color.core.red.600        color.core.red.400
color.border.success        color.core.kiwi.600        color.core.kiwi.500
color.border.inverse        color.core.neutral.100        color.core.neutral.900
color.border.onAccent        color.core.neutral.100        color.core.neutral.800
color.border.onAttention        color.core.neutral.100        color.core.neutral.800
color.border.onSuccess        color.core.neutral.100        color.core.neutral.800
color.border.onInverse        color.core.neutral.100        color.core.neutral.800
color.border.onDisabled        color.core.neutral.100        color.core.neutral.800
color.border.disabled        color.core.neutral.400        color.core.neutral.700
Gradient
Title        Value on light        Value on dark
color.gradient.imageScrim        -        -
color.gradient.ai.fullColorDiagonal        color.ai.solid.green.strong @ 10%color.ai.solid.blue.strong @ 27%color.ai.solid.purple.strong @ 42%color.ai.solid.red.strong @ 56%color.ai.solid.yellow.strong @ 78%        color.ai.solid.green.strong @ 10%color.ai.solid.blue.strong @ 27%color.ai.solid.purple.strong @ 42%color.ai.solid.red.strong @ 56%color.ai.solid.yellow.strong @ 78%
color.gradient.ai.green.strong        color.ai.solid.blue.strong @ 0%color.ai.solid.green.strong @ 100%        color.ai.solid.blue.strong @ 0%color.ai.solid.green.strong @ 100%
color.gradient.ai.green.subtle        color.ai.solid.blue.subtle @ 0%color.ai.solid.green.subtle @ 100%        color.ai.solid.blue.subtle @ 0%color.ai.solid.green.subtle @ 100%
color.gradient.ai.blue.strong        color.ai.solid.purple.strong @ 0%color.ai.solid.blue.strong @ 50%color.ai.solid.green.strong @ 100%        color.ai.solid.purple.strong @ 0%color.ai.solid.blue.strong @ 50%color.ai.solid.green.strong @ 100%
color.gradient.ai.blue.subtle        color.ai.solid.purple.subtle @ 0%color.ai.solid.blue.subtle @ 50%color.ai.solid.green.subtle @ 100%        color.ai.solid.purple.subtle @ 0%color.ai.solid.blue.subtle @ 50%color.ai.solid.green.subtle @ 100%
color.gradient.ai.purple.strong        color.ai.solid.red.strong @ 0%color.ai.solid.purple.strong @ 100%        color.ai.solid.red.strong @ 0%color.ai.solid.purple.strong @ 100%
color.gradient.ai.purple.subtle        color.ai.solid.red.subtle @ 0%color.ai.solid.purple.subtle @ 100%        color.ai.solid.red.subtle @ 0%color.ai.solid.purple.subtle @ 100%
Expressive theme
Title        Background        Foreground
expressiveTheme.avocado.light        color.core.avocado.400        color.core.avocado.700
expressiveTheme.avocado.medium        color.core.avocado.500        color.core.avocado.700
expressiveTheme.avocado.dark        color.core.avocado.700        color.core.avocado.200
expressiveTheme.blue.light        color.core.blue.400        color.core.blue.800
expressiveTheme.blue.medium        color.core.blue.500        color.core.blue.100
expressiveTheme.blue.dark        color.core.blue.700        color.core.blue.200
expressiveTheme.coral.light        color.core.coral.400        color.core.coral.800
expressiveTheme.coral.medium        color.core.coral.500        color.core.coral.800
expressiveTheme.coral.dark        color.core.coral.700        color.core.coral.200
expressiveTheme.dijon.light        color.core.dijon.400        color.core.dijon.700
expressiveTheme.dijon.medium        color.core.dijon.500        color.core.dijon.700
expressiveTheme.dijon.dark        color.core.dijon.700        color.core.dijon.200
expressiveTheme.green.light        color.core.green.400        color.core.green.700
expressiveTheme.green.medium        color.core.green.500        color.core.green.700
expressiveTheme.green.dark        color.core.green.700        color.core.green.200
expressiveTheme.indigo.light        color.core.indigo.400        color.core.indigo.800
expressiveTheme.indigo.medium        color.core.indigo.500        color.core.indigo.800
expressiveTheme.indigo.dark        color.core.indigo.700        color.core.indigo.200
expressiveTheme.jade.light        color.core.jade.400        color.core.jade.800
expressiveTheme.jade.medium        color.core.jade.500        color.core.jade.800
expressiveTheme.jade.dark        color.core.jade.700        color.core.jade.200
expressiveTheme.kiwi.light        color.core.kiwi.400        color.core.kiwi.800
expressiveTheme.kiwi.medium        color.core.kiwi.500        color.core.kiwi.800
expressiveTheme.kiwi.dark        color.core.kiwi.700        color.core.kiwi.200
expressiveTheme.lilac.light        color.core.lilac.400        color.core.lilac.800
expressiveTheme.lilac.medium        color.core.lilac.500        color.core.lilac.100
expressiveTheme.lilac.dark        color.core.lilac.700        color.core.lilac.200
expressiveTheme.live.light        color.core.violet.600        color.core.violet.100
expressiveTheme.live.medium        color.core.violet.600        color.core.violet.100
expressiveTheme.live.dark        color.core.violet.600        color.core.violet.100
expressiveTheme.marigold.light        color.core.marigold.400        color.core.marigold.700
expressiveTheme.marigold.medium        color.core.marigold.500        color.core.marigold.700
expressiveTheme.marigold.dark        color.core.marigold.700        color.core.marigold.200
expressiveTheme.neutral.light        color.core.neutral.200        color.core.neutral.800
expressiveTheme.neutral.medium        color.core.neutral.200        color.core.neutral.800
expressiveTheme.neutral.dark        color.core.neutral.800        color.core.neutral.100
expressiveTheme.orange.light        color.core.orange.400        color.core.orange.700
expressiveTheme.orange.medium        color.core.orange.500        color.core.orange.800
expressiveTheme.orange.dark        color.core.orange.700        color.core.orange.200
expressiveTheme.pink.light        color.core.pink.400        color.core.pink.800
expressiveTheme.pink.medium        color.core.pink.500        color.core.pink.800
expressiveTheme.pink.dark        color.core.pink.700        color.core.pink.200
expressiveTheme.red.light        color.core.red.400        color.core.red.700
expressiveTheme.red.medium        color.core.red.500        color.core.red.800
expressiveTheme.red.dark        color.core.red.700        color.core.red.200
expressiveTheme.teal.light        color.core.teal.400        color.core.teal.700
expressiveTheme.teal.medium        color.core.teal.500        color.core.teal.700
expressiveTheme.teal.dark        color.core.teal.700        color.core.teal.200
expressiveTheme.violet.light        color.core.violet.400        color.core.violet.800
expressiveTheme.violet.medium        color.core.violet.500        color.core.violet.200
expressiveTheme.violet.dark        color.core.violet.700        color.core.violet.200
expressiveTheme.yellow.light        color.core.yellow.400        color.core.yellow.700
expressiveTheme.yellow.medium        color.core.yellow.500        color.core.yellow.700
expressiveTheme.yellow.dark        color.core.yellow.700        color.core.yellow.200