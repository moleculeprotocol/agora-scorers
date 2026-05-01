export class ReplayError extends Error {
  constructor(message, nextAction, code = "replay_error") {
    super(`${message} Next step: ${nextAction}`);
    this.name = "ReplayError";
    this.code = code;
    this.nextAction = nextAction;
  }
}

export function fail(message, nextAction, code) {
  throw new ReplayError(message, nextAction, code);
}

export function formatError(error) {
  if (error instanceof ReplayError) {
    return error.message;
  }
  if (error instanceof Error && error.message) {
    return `${error.message} Next step: rerun with a current public proof CID, verify Docker is available, and retry.`;
  }
  return "Replay failed for an unknown reason. Next step: rerun with a current public proof CID and retry.";
}
