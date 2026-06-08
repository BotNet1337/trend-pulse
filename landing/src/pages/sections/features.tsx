import { CalendarClock, FileCheck, Image, LayoutDashboard, Share2, SlidersHorizontal } from 'lucide-react';

export function FeaturesSection() {
  const features = [
    {
      icon: Share2,
      title: 'Publish everywhere',
      description: 'Compose once and send posts to the social networks you connect—fewer copy-paste cycles.',
    },
    {
      icon: CalendarClock,
      title: 'Schedule & calendar',
      description: 'Queue content and publish at the right time for each platform from a single calendar view.',
    },
    {
      icon: LayoutDashboard,
      title: 'One dashboard',
      description: 'See connected channels, drafts, and what is live without jumping between native apps.',
    },
    {
      icon: Image,
      title: 'Rich posts',
      description: 'Add images and media where each network allows; we keep platform constraints in mind.',
    },
    {
      icon: SlidersHorizontal,
      title: 'Per-platform tweaks',
      description: 'Adjust captions, hashtags, and formatting so each post fits the network it lands on.',
    },
    {
      icon: FileCheck,
      title: 'Clear baseline policies',
      description: 'Privacy, terms, and acceptable use are documented from day one.',
    },
  ];

  return (
    <section className="py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Everything you need to ship social content</h2>
          <p className="text-lg text-muted-foreground max-w-2xl mx-auto">
            Plan, publish, and stay consistent across platforms from one workspace instead of a dozen tabs.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
          {features.map((feature) => {
            const Icon = feature.icon;
            return (
              <div key={feature.title} className="group">
                <div className="bg-card border border-border rounded-lg p-6 h-full transition-all hover:shadow-md hover:border-primary/50">
                  <div className="w-12 h-12 bg-primary/10 rounded-lg flex items-center justify-center mb-4 group-hover:bg-primary/20 transition-colors">
                    <Icon className="h-6 w-6 text-primary" />
                  </div>
                  <h3 className="mb-2">{feature.title}</h3>
                  <p className="text-sm text-muted-foreground">{feature.description}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
