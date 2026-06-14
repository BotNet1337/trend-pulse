export function SocialProofSection() {
  const placeholderLogos = Array.from({ length: 5 }, (_, i) => i + 1);

  return (
    <section className="py-14 px-6 lg:px-20 border-y border-white/10 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <p className="text-center text-xs uppercase tracking-[0.12em] text-[color:var(--aurora-text-faint)] mb-8">
          Trusted by teams who publish everywhere
        </p>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-5 items-center justify-items-center">
          {placeholderLogos.map((logo) => (
            <div key={logo} className="fs-glass flex h-12 w-32 items-center justify-center opacity-60">
              <span className="text-xs text-muted-foreground">Logo {logo}</span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}


