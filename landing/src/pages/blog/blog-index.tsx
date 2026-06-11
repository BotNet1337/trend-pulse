import { Link } from '@tanstack/react-router';
import { BLOG_ARTICLES } from '@/shared/blog/articles';
import { formatBlogDate } from '@/shared/blog/format-date';
import { SITE } from '@/shared/site/constants';

/** TASK-073: minimal blog index — a list of the published articles. */
export function BlogIndexPage() {
  return (
    <div className="pt-24 pb-16 px-6 lg:px-20">
      <div className="max-w-3xl mx-auto">
        <div className="mb-12">
          <h1 className="text-4xl md:text-5xl font-bold mb-4 tracking-tight">Blog</h1>
          <p className="text-muted-foreground">
            Guides on early viral content detection in public Telegram channels, honest tool
            comparisons, and practical notes from building {SITE.brandName}.
          </p>
        </div>

        <ul className="space-y-8">
          {BLOG_ARTICLES.map((article) => (
            <li key={article.slug} className="border border-border rounded-xl p-6 bg-card">
              <Link
                to={article.path}
                className="text-xl font-semibold hover:text-primary transition-colors"
              >
                {article.title}
              </Link>
              <p className="text-sm text-muted-foreground mt-2">
                {formatBlogDate(article.datePublished)} · {article.readingTimeMinutes} min read
              </p>
              <p className="text-muted-foreground mt-3">{article.excerpt}</p>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
