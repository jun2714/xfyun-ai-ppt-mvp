import { FirstSlidePreview } from "./FirstSlidePreview";

export default async function PresentationThumbnailPage({
  searchParams,
}: {
  searchParams: Promise<{ id?: string }>;
}) {
  const { id = "" } = await searchParams;
  return <FirstSlidePreview presentationId={id} />;
}
