import { Component, type ReactNode } from "react";

interface ChartErrorBoundaryProps {
    children: ReactNode;
    fallback: ReactNode;
    /**
     * When this value changes (compared by `!==`) the boundary re-arms after a crash.
     * The renderer passes the chart's `traces` array, so a card that crashed on early
     * partial data during live preview recovers when new data arrives under the SAME
     * chart id. React Query keeps the reference stable while content is unchanged, so
     * this does NOT retry a perpetually-failing chart on every poll.
     */
    resetKey?: unknown;
}

interface ChartErrorBoundaryState {
    crashed: boolean;
}

/**
 * Catches SYNCHRONOUS render / lifecycle errors thrown below it — including a failed
 * `React.lazy` chunk load (e.g. a stale chunk after a deploy) and a synchronous throw
 * from react-plotly.js — and shows `fallback` instead of crashing the surrounding
 * module.
 *
 * ASYNCHRONOUS plotly.js draw failures are NOT caught here: React error boundaries
 * never catch errors thrown outside the render/lifecycle cycle (e.g. inside the
 * `Plotly.react` promise). Those are handled separately by the `onError` prop on the
 * Plot component. Sibling of `ExhibitErrorBoundary` — kept as its own component so the
 * working exhibit path is left untouched.
 */
export class ChartErrorBoundary extends Component<
    ChartErrorBoundaryProps,
    ChartErrorBoundaryState
> {
    state: ChartErrorBoundaryState = { crashed: false };

    static getDerivedStateFromError(): ChartErrorBoundaryState {
        return { crashed: true };
    }

    componentDidUpdate(prevProps: ChartErrorBoundaryProps) {
        if (this.state.crashed && prevProps.resetKey !== this.props.resetKey) {
            this.setState({ crashed: false });
        }
    }

    render() {
        return this.state.crashed ? this.props.fallback : this.props.children;
    }
}
