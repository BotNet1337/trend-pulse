import { Accordion, AccordionItem } from '@/shared/components/accordion';
import { Link } from '@tanstack/react-router';
import { SITE } from '@/shared/site/constants';

export function FaqSection() {
  const brand = SITE.brandName;
  const faqs = [
    {
      question: `What is ${brand}?`,
      answer: `${brand} helps you plan, schedule, and publish posts to multiple social platforms from one workspace—so you spend less time switching apps and more time on the content itself.`,
    },
    {
      question: `Is ${brand} currently available?`,
      answer: `${brand} is currently in early access development. We're actively building features and onboarding early users. Join the waitlist and we'll reach out when access is available.`,
    },
    {
      question: 'How does pricing work?',
      answer:
        "Pricing is evolving during early access. We'll publish concrete plans as the product stabilizes. If you need a custom agreement, contact us.",
    },
    {
      question: 'Which social platforms are supported?',
      answer:
        'We are expanding integrations during early access. Join the waitlist for the current list of networks and what is planned next.',
    },
    {
      question: 'Is my data secure and private?',
      answer:
        'We aim to follow reasonable security practices and a privacy-first baseline. Your content and connected accounts are not sold for marketing, and we keep policies transparent. Please review our Security and Privacy pages for current details.',
    },
    {
      question: 'Can I use images or video in posts?',
      answer:
        'Yes—rich media is core to social publishing. Supported formats and limits depend on each platform and will evolve as we ship.',
    },
    {
      question: 'What happens to my drafts and scheduled posts?',
      answer:
        'Drafts and scheduled posts are part of the core experience. Details like retention, export, and history can evolve during early access.',
    },
    {
      question: `Can I use ${brand} for my business?`,
      answer:
        "Yes. We can discuss business needs and custom agreements during early access. Contact us and we'll figure out the right setup.",
    },
    {
      question: 'What if pricing changes after I sign up?',
      answer:
        "Early access terms can change as the product evolves. We'll communicate material changes through updated policies and announcements.",
    },
    {
      question: 'How can I contact support?',
      answer:
        'You can reach our support team through the contact form on our website, or email us directly. Pro and Enterprise customers receive priority support with faster response times.',
    },
    {
      question: 'Do you offer refunds?',
      answer:
        'Please review our Refund Policy. If paid plans are introduced, the policy will be updated with concrete terms.',
    },
    {
      question: 'Will there be an API?',
      answer:
        'Yes—API access for integrations and publishing workflows is planned. Scope and availability will be published as the product stabilizes.',
    },
  ];

  return (
    <section id="faq" className="py-24 px-6 lg:px-20 snap-start scroll-mt-16">
      <div className="max-w-3xl mx-auto">
        <div className="text-center mb-16">
          <h2 className="text-3xl md:text-4xl font-bold mb-4">Frequently Asked Questions</h2>
          <p className="text-lg text-muted-foreground">Everything you need to know about {brand}</p>
        </div>

        <Accordion>
          {faqs.map((faq, index) => (
            <AccordionItem key={faq.question} title={faq.question} defaultOpen={index === 0}>
              <p>{faq.answer}</p>
            </AccordionItem>
          ))}
        </Accordion>

        <div className="mt-12 text-center">
          <p className="text-muted-foreground mb-4">Still have questions?</p>
          <Link to="/contact" className="text-primary hover:underline">
            Contact our team →
          </Link>
        </div>
      </div>
    </section>
  );
}
