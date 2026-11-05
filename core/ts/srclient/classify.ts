// Sort a /api/pricing row into a category. Mirrors core/python/srclient/classify.py.

export const CATEGORIES = ['language', 'image', 'video', 'music', 'audio', 'embedding', 'rerank'] as const;
export type Category = (typeof CATEGORIES)[number];

export interface PricingRow {
	model_name: string;
	tags?: string | null;
	supported_endpoint_types?: string[] | null;
	description?: string | null;
}

export interface Family {
	label: string;
	category: Category;
	match: string[];
	default?: string | null;
}

export interface VideoRule {
	style: 'top' | 'metadata';
	resolutions: string[];
	seconds: { min?: number; max?: number; values?: number[] };
	start_image: 'optional' | 'required' | 'none';
	image_key: string;
}

export interface ShippedModel {
	name: string;
	category: Category;
	family: string | null;
}

function tags(row: PricingRow): Set<string> {
	return new Set(
		String(row.tags ?? '')
			.split(',')
			.map((t) => t.trim())
			.filter(Boolean),
	);
}

export function classify(row: PricingRow, overrides: Record<string, string> = {}): Category {
	const name = row.model_name ?? '';
	if (Object.prototype.hasOwnProperty.call(overrides, name)) return overrides[name] as Category;
	const t = tags(row);
	const endpoints = new Set(row.supported_endpoint_types ?? []);
	if (t.has('Video') || endpoints.has('openai-video')) return 'video';
	if (t.has('Image') || t.has('Midjourney')) return 'image';
	if (t.has('Music')) return 'music';
	if (t.has('Audio')) return 'audio';
	if (t.has('Embedding') || endpoints.has('embeddings')) return 'embedding';
	if (t.has('Rerank') || endpoints.has('jina-rerank')) return 'rerank';
	return 'language';
}

export function matchesAny(name: string, patterns: readonly string[]): boolean {
	return patterns.some((p) => new RegExp(p).test(name));
}

export function familyOf(name: string, families: Record<string, Family>): string | null {
	for (const [key, family] of Object.entries(families)) {
		if (matchesAny(name, family.match)) return key;
	}
	return null;
}
