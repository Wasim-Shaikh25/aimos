import { useEffect, useRef } from 'react';
import { createChart, LineSeries } from 'lightweight-charts';

export default function EquityChart({ data }) {
  const chartRef = useRef(null);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current || !data?.length) return;

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 300,
      layout: { background: { type: 'solid', color: '#0b0f19' }, textColor: '#c9d1d9' },
      grid: { vertLines: { color: '#1f2937' }, horzLines: { color: '#1f2937' } },
      timeScale: { timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;

    const line = chart.addSeries(LineSeries, { color: '#22c55e', lineWidth: 2 });
    const points = data.map((v, i) => ({ time: i, value: Number(v) || 0 }));
    line.setData(points);
    chart.timeScale().fitContent();

    const onResize = () => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    };
    window.addEventListener('resize', onResize);

    return () => {
      window.removeEventListener('resize', onResize);
      chart.remove();
    };
  }, [data]);

  return <div ref={containerRef} style={{ width: '100%', height: 300 }} />;
}
