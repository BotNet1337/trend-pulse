import * as React from 'react';
import { Link } from '@tanstack/react-router';
import type { BlogArticleMeta } from '@/shared/blog/articles';
import { formatBlogDate } from '@/shared/blog/format-date';

/**
 * TASK-073: generic blog article renderer — the blog twin of
 * `pages/legal/legal-page.tsx` (prose instead of an accordion).
 */
export function BlogArticleLayout(props: { meta: BlogArticleMeta; children: React.ReactNode }) {
  return (
    <div className="pt-24 pb-16 px-6 lg:px-20">
      <article className="max-w-3xl mx-auto">
        <div className="mb-10">
          <Link to="/blog" className="text-sm text-primary hover:underline">
            ← Blog
          </Link>
          <h1 className="text-4xl md:text-5xl font-bold mt-4 mb-4 tracking-[-0.02em] fs-grad-text">
            {props.meta.title}
          </h1>
          <p className="text-muted-foreground text-sm">
            {formatBlogDate(props.meta.datePublished)} · {props.meta.readingTimeMinutes} min read
          </p>
        </div>

        <div className="space-y-6 leading-relaxed text-foreground/90 [&_h2]:text-2xl [&_h2]:font-semibold [&_h2]:tracking-tight [&_h2]:mt-10 [&_h2]:mb-2 [&_ul]:list-disc [&_ul]:pl-6 [&_ul]:space-y-2 [&_ol]:list-decimal [&_ol]:pl-6 [&_ol]:space-y-2 [&_strong]:text-foreground">
          {props.children}
        </div>

        <div className="mt-12 pt-8 border-t border-white/10 flex flex-col sm:flex-row gap-4 sm:items-center sm:justify-between">
          <Link to="/blog" className="text-sm text-primary hover:underline">
            ← All articles
          </Link>
          <Link to="/pricing" className="text-sm text-primary hover:underline">
            See plans and pricing →
          </Link>
        </div>
      </article>
    </div>
  );
}
