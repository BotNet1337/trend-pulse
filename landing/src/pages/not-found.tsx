import { Container } from '@/shared/components/container';
import { Link } from '@tanstack/react-router';
import { Button } from '@/shared/components/button';

export function NotFoundPage() {
  return (
    <Container className="py-14">
      <h1 className="text-3xl font-semibold tracking-tight text-neutral-900 dark:text-neutral-50">Page not found</h1>
      <p className="mt-4 text-neutral-700 dark:text-neutral-300">
        The page you requested does not exist.
      </p>
      <div className="mt-8">
        <Link to="/">
          <Button>Go home</Button>
        </Link>
      </div>
    </Container>
  );
}


