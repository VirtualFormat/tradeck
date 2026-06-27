interface Props {
  value: number;
  prefix?: string;
}

export function DotMatrixNumber({ value, prefix = '$' }: Props): JSX.Element {
  const tone = value >= 0 ? 'text-up' : 'text-down';
  const formatted = Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 0 });
  return (
    <div className={`tab-nums font-mono leading-none ${tone}`} style={{ fontSize: '3.25rem' }}>
      {value < 0 ? '-' : ''}
      {prefix}
      {formatted}
    </div>
  );
}
