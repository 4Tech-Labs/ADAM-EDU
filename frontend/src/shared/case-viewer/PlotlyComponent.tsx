import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js/lib/core";
import bar from "plotly.js/lib/bar";
import box from "plotly.js/lib/box";
import heatmap from "plotly.js/lib/heatmap";
import scatter from "plotly.js/lib/scatter";
import violin from "plotly.js/lib/violin";
import waterfall from "plotly.js/lib/waterfall";

// Partial Plotly build: only these six trace modules are bundled. Their trace `type`s
// are mirrored in `REGISTERED_TRACE_TYPES` (plotlyChartUtils.ts), which sanitizeTraces
// uses to drop any trace whose type has no module here (it would otherwise render
// nothing). Keep the two lists in sync — the const-lock test in plotlyChartUtils.test.ts
// fails if `REGISTERED_TRACE_TYPES` changes without a conscious update. The names are
// kept in plotlyChartUtils (plotly-free) so this heavy bundle stays out of the eager chunk.
Plotly.register([bar, box, heatmap, scatter, violin, waterfall]);

const PlotlyComponent = createPlotlyComponent(Plotly);

export default PlotlyComponent;
