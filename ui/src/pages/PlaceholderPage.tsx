interface PlaceholderPageProps {
  title: string;
  description?: string;
}

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2">
      <h1 className="text-xl text-text-muted">{title}</h1>
      {description && (
        <p className="text-sm text-text-dim">{description}</p>
      )}
    </div>
  );
}
