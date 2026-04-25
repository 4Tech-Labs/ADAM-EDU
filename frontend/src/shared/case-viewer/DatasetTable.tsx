import { useState } from "react";

interface DatasetTableProps {
    data: Record<string, unknown>[];
    pageSize?: number;
}

export function DatasetTable({ data, pageSize = 50 }: DatasetTableProps) {
    const [currentPage, setCurrentPage] = useState(1);

    if (!data || data.length === 0) return null;

    const totalRows = data.length;
    const totalPages = Math.ceil(totalRows / pageSize);
    const startIndex = (currentPage - 1) * pageSize;
    const currentData = data.slice(startIndex, startIndex + pageSize);

    // Extract headers from the first object
    const headers = Object.keys(data[0]);

    const handlePrev = () => setCurrentPage((p) => Math.max(1, p - 1));
    const handleNext = () => setCurrentPage((p) => Math.min(totalPages, p + 1));

    const renderCell = (val: unknown) => {
        if (val === null || val === undefined) {
            return <span className="inline-block px-1.5 py-0.5 bg-slate-100 text-slate-400 text-[10px] uppercase font-bold rounded">null</span>;
        }
        if (typeof val === "number") {
            // For numbers, use toLocaleString but keep decimals if any
            return <span className="text-emerald-700 font-mono text-xs">{val.toLocaleString('en-US', { maximumFractionDigits: 4 })}</span>;
        }
        if (typeof val === "boolean") {
            return <span className={`text-xs font-mono font-bold ${val ? 'text-indigo-600' : 'text-slate-500'}`}>{val.toString()}</span>;
        }
        return <span className="text-slate-700 text-xs truncate max-w-[200px] block" title={String(val)}>{String(val)}</span>;
    };

    return (
        <div className="w-full my-8 border border-slate-200 rounded-xl overflow-hidden bg-white shadow-sm">
            <div className="bg-slate-50 px-4 py-3 border-b border-slate-200 flex justify-between items-center">
                <div>
                    <h3 className="font-bold text-slate-800 text-sm">Dataset de Análisis</h3>
                    <p className="text-xs text-slate-500 mt-0.5">{totalRows.toLocaleString()} registros extraídos del caso</p>
                </div>
                {totalPages > 1 && (
                    <div className="flex items-center gap-3">
                        <span className="text-xs text-slate-500 font-medium">
                            {startIndex + 1}-{Math.min(startIndex + pageSize, totalRows)} de {totalRows}
                        </span>
                        <div className="flex items-center bg-white border border-slate-200 rounded-lg overflow-hidden shadow-sm">
                            <button
                                onClick={handlePrev}
                                disabled={currentPage === 1}
                                className="px-2 py-1 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:hover:bg-transparent transition-colors border-r border-slate-200"
                            >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
                                </svg>
                            </button>
                            <button
                                onClick={handleNext}
                                disabled={currentPage === totalPages}
                                className="px-2 py-1 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:hover:bg-transparent transition-colors"
                            >
                                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                </svg>
                            </button>
                        </div>
                    </div>
                )}
            </div>
            
            <div className="overflow-x-auto w-full">
                <table className="w-full text-left border-collapse min-w-max">
                    <thead className="bg-[#0f172a] text-white">
                        <tr>
                            <th className="py-2.5 px-4 text-[10px] font-bold uppercase tracking-wider text-slate-300 border-b border-slate-700 w-12 text-center">#</th>
                            {headers.map((h, i) => (
                                <th key={i} className="py-2.5 px-4 text-[10px] font-bold uppercase tracking-wider text-slate-200 border-b border-slate-700">
                                    {h}
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100">
                        {currentData.map((row, r_idx) => (
                            <tr key={r_idx} className="hover:bg-slate-50/80 transition-colors">
                                <td className="py-2 px-4 text-[10px] font-mono text-slate-400 text-center bg-slate-50">
                                    {startIndex + r_idx + 1}
                                </td>
                                {headers.map((h, c_idx) => (
                                    <td key={c_idx} className="py-2 px-4 whitespace-nowrap">
                                        {renderCell(row[h])}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {totalPages > 1 && (
                <div className="bg-slate-50 px-4 py-2.5 border-t border-slate-200 text-xs text-center text-slate-500">
                    Página {currentPage} de {totalPages}
                </div>
            )}
        </div>
    );
}
