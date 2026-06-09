import { HeroSection } from './sections/hero';
import { SocialProofSection } from './sections/social-proof';
import { FeaturesSection } from './sections/features';
import { HowItWorksSection } from './sections/how-it-works';
import { SecurityPrivacySection } from './sections/security-privacy';
import { PricingPreviewSection } from './sections/pricing-preview';
import { FaqSection } from './sections/faq';
import { FinalCtaSection } from './sections/final-cta';

export function HomePage() {
  return (
    <>
      <HeroSection />
      <SocialProofSection />
      <FeaturesSection />
      <HowItWorksSection />
      <SecurityPrivacySection />
      <PricingPreviewSection />
      <FaqSection />
      <FinalCtaSection />
    </>
  );
}
