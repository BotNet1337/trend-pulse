import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { createElement, type ComponentType } from 'react';
import { render } from '@react-email/render';
import { z } from 'zod';
import type { AppConfig } from './config.js';
import type { RegistryEntry } from './types.js';
import { applyTransform, interpolate } from './utils.js';

const templateDefinitionSchema = z.object({
  eventName: z.string().min(1),
  templatePath: z.string().min(1),
  subject: z.string().min(1),
  schema: z.record(z.string(), z.unknown()),
  transform: z.record(z.string(), z.string()).optional(),
  previewDefaults: z.record(z.string(), z.unknown()),
});

const templatesFileSchema = z.array(templateDefinitionSchema);

export type TemplateDefinition = z.infer<typeof templateDefinitionSchema>;

const __dirname = dirname(fileURLToPath(import.meta.url));

function isReactComponent(value: unknown): value is ComponentType<Record<string, unknown>> {
  return typeof value === 'function';
}

async function loadComponent(
  templatePath: string,
): Promise<ComponentType<Record<string, unknown>>> {
  const basePath = join(__dirname, '..', 'src', 'templates', templatePath);

  let mod: unknown;
  try {
    mod = await import(`${basePath}.js`);
  } catch {
    mod = await import(`${basePath}.tsx`);
  }

  if (typeof mod !== 'object' || mod === null) {
    throw new Error(`Module "${templatePath}" did not return an object`);
  }

  const component = Object.values(mod).find(isReactComponent);

  if (!component) {
    throw new Error(`No component export found in "${templatePath}"`);
  }

  return component;
}

export async function loadRegistry(
  schemaPath: string,
): Promise<Record<string, RegistryEntry>> {
  const raw = readFileSync(schemaPath, 'utf8');
  const definitions = templatesFileSchema.parse(JSON.parse(raw));
  const registry: Record<string, RegistryEntry> = {};

  for (const def of definitions) {
    const Component = await loadComponent(def.templatePath);

    registry[def.templatePath] = {
      schema: z.fromJSONSchema(def.schema),
      Component,
      subject: def.subject,
      transformMap: def.transform ?? null,
      previewDefaults: def.previewDefaults,
    };
  }

  return registry;
}

export async function renderEntry(
  entry: RegistryEntry,
  props: Record<string, unknown>,
  config: AppConfig,
): Promise<{ html: string; subject: string }> {
  const componentProps = applyTransform(entry.transformMap, props, config);
  const subject = interpolate(entry.subject, props, config);
  const html = await render(createElement(entry.Component, componentProps));
  return { html, subject };
}
