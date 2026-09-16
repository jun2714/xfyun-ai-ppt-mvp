// Read the persisted terminal state only. Never reopen an outline stream: that
// could generate another paid outline on older servers.
export async function readOutlineFailure(apiBase, presentationId, { fetchImpl = fetch } = {}) {
  try {
    const response = await fetchImpl(
      `${apiBase}/presentation/${encodeURIComponent(presentationId)}`,
      { method: 'GET', signal: AbortSignal.timeout(10000) },
    );
    if (!response.ok) return null;
    const body = await response.json();
    const metadata = body?.generation_metadata;
    if (metadata?.outline_status !== 'failed') return null;
    return {
      state: 'failed',
      detail: typeof metadata.outline_error === 'string' ? metadata.outline_error : '',
    };
  } catch {
    // A failed diagnostic read must never replace the original probe failure.
    return null;
  }
}
