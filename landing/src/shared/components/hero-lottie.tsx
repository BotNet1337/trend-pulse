import * as React from 'react';
import LottieImport from 'lottie-react';
import animationData from '@/shared/animations/hero-orb.json';

type MaybeDefault<T> = T | { default: T };

function unwrapDefault<T>(value: MaybeDefault<T>): T {
  return typeof value === 'object' && value !== null && 'default' in value ? (value as { default: T }).default : (value as T);
}

const LottieComponent = unwrapDefault(LottieImport as unknown as MaybeDefault<typeof LottieImport>);
const heroAnimationData = unwrapDefault(animationData as unknown as MaybeDefault<typeof animationData>);

export function HeroLottie(props: { className?: string }) {
  const [mounted, setMounted] = React.useState(false);

  React.useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) return null;

  return (
    <div className={props.className}>
      <LottieComponent animationData={heroAnimationData} loop autoplay />
    </div>
  );
}


