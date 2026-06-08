export function SocialProofSection() {
  const placeholderLogos = Array.from({ length: 5 }, (_, i) => i + 1);

  return (
    <section className="py-16 px-6 lg:px-20 border-y border-border bg-muted/20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <p className="text-center text-sm text-muted-foreground mb-8">Trusted by teams who publish everywhere</p>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-8 items-center justify-items-center opacity-50">
          {placeholderLogos.map((logo) => (
            <div key={logo} className="w-32 h-12 bg-muted rounded flex items-center justify-center">
              <span className="text-xs text-muted-foreground">Logo {logo}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}


