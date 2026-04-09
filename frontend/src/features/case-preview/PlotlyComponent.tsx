import createPlotlyComponent from "react-plotly.js/factory";
import Plotly from "plotly.js/lib/core";
import bar from "plotly.js/lib/bar";
import box from "plotly.js/lib/box";
import heatmap from "plotly.js/lib/heatmap";
import scatter from "plotly.js/lib/scatter";
import violin from "plotly.js/lib/violin";
import waterfall from "plotly.js/lib/waterfall";

Plotly.register([bar, box, heatmap, scatter, violin, waterfall]);

const PlotlyComponent = createPlotlyComponent(Plotly);

export default PlotlyComponent;
