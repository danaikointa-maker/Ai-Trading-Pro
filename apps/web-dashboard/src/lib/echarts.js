// One place that registers only the ECharts pieces this dashboard actually uses.
//
// `import * as echarts from 'echarts'` pulls the whole library (~1 MB) into the
// bundle. Both of our charts are line/area charts with a grid, an axis tooltip
// and a markLine reference, so importing from `echarts/core` cuts that down
// massively — and registering here means the two chart components cannot drift
// into registering different feature sets.
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, MarkLineComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([LineChart, GridComponent, MarkLineComponent, TooltipComponent, CanvasRenderer])

export { echarts }
export default echarts
