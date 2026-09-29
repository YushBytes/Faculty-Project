import { ProductPage } from "@/components/product-page";
export default async function Page({ params }: { params: Promise<{ id: string }> }) { const { id } = await params; return <ProductPage section="interventions" id={id} />; }
