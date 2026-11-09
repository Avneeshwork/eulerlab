/**
 * Plain words for an agent task card (ADR-159). The task file speaks in the
 * agents' own terms (`fix_code`, `head_platform`, "Watchdog: task overdue
 * since …: Watchdog: …"); the card on the page says, for someone who does not
 * code: what the task is for, why it was raised, whether it needs you, and
 * what each button does. Kept apart from the component so `npm test` can pin it.
 */

export type TaskLike = {
  title: string;
  owner: string;
  created_by: string;
  kind: string;
  status: string;
  parent: string;
};

export type Action = 'run' | 'retry' | 'send_back' | 'close' | 'cancel' | 'assist';

/** An agent's display name: its title from the org chart, else the name tidied. */
export function who(name: string, titles: Map<string, string>): string {
  if (name === 'ceo') return 'you';
  if (name === 'operator') return 'you (from the terminal)';
  if (name === 'doctor') return 'the doctor, which checks every run as it ends';
  if (name === 'work') return 'the task runner';
  const title = titles.get(name);
  if (title) return title;
  return name.replace(/^head_/, 'head of ').replace(/_/g, ' ');
}

const LATE = /^task overdue since (\d{4}-\d{2}-\d{2}):\s*/i;
const WATCHDOG = /^watchdog:\s*/i;

/**
 * A title without the watchdog's stacked prefixes. "Watchdog: task overdue
 * since 2026-11-06: Watchdog: task overdue since 2026-11-05: Optimize …"
 * becomes { text: "Optimize …", lateSince: "2026-11-05", watchdog: true }.
 */
export function plainTitle(title: string): {
  text: string;
  lateSince: string;
  watchdog: boolean;
} {
  let text = title.trim();
  let lateSince = '';
  let watchdog = false;
  // The watchdog cuts the late task's title at 120 characters, and a task title
  // stops at 200: show that the end is missing rather than a word cut short.
  let cut = title.length >= 200;
  for (;;) {
    const w = WATCHDOG.exec(text);
    if (w) {
      watchdog = true;
      text = text.slice(w[0].length);
      continue;
    }
    const l = LATE.exec(text);
    if (l) {
      lateSince = l[1];
      text = text.slice(l[0].length);
      if (text.length === 120) cut = true;
      continue;
    }
    break;
  }
  return { text: (text || title) + (cut ? '…' : ''), lateSince, watchdog };
}

/** The headline a person reads first. */
export function headline(task: TaskLike): string {
  const p = plainTitle(task.title);
  if (p.lateSince) return `Find out why a task is late: “${p.text}”`;
  if (p.watchdog) return `Look into a problem: ${p.text}`;
  return p.text;
}

/** Why the task exists, in one sentence. */
export function whyRaised(task: TaskLike, titles: Map<string, string>, parentTitle = ''): string {
  const p = plainTitle(task.title);
  if (task.created_by === 'ceo') return 'You asked for this.';
  if (task.created_by === 'watchdog') {
    if (p.lateSince)
      return `The watchdog, which checks that the other agents keep working, saw a task still unfinished since ${p.lateSince} and passed it to ${who(task.owner, titles)} to sort out.`;
    return `The watchdog, which checks that the other agents keep working, spotted this problem and passed it to ${who(task.owner, titles)}.`;
  }
  if (task.created_by === 'doctor') return 'A run crashed, so the doctor raised this to get the code fixed.';
  if (task.created_by.startsWith('head_')) {
    const from = parentTitle ? ` “${headline({ ...task, title: parentTitle })}”` : ' a bigger task';
    return `${who(task.created_by, titles)} broke${from} into steps; this is one of them.`;
  }
  return `${who(task.created_by, titles)} asked for this.`;
}

/** What doing the task means: the skill's own sentence, or the head's job. */
export function whatItDoes(task: TaskLike, skillWhat: string, titles: Map<string, string>): string {
  if (task.owner.startsWith('head_') && !task.kind)
    return `${who(task.owner, titles)} decides which agents should work on this, hands them the steps, and checks what comes back.`;
  if (skillWhat) return `${who(task.owner, titles)} will: ${skillWhat.charAt(0).toLowerCase()}${skillWhat.slice(1)}.`;
  return `${who(task.owner, titles)} works on it.`;
}

/**
 * Whether the task waits for you, and what you would do. `auto` is the skill's
 * flag: false means no agent may start it (it spends trials or a paid model).
 */
export function needsYou(
  task: TaskLike,
  opts: { auto: boolean | undefined; stuckSteps: boolean },
): { yes: boolean; text: string } {
  const head = task.owner.startsWith('head_');
  if (task.status === 'blocked')
    return {
      yes: true,
      text: 'It is stuck. Ask AI for help, retry it, or cancel it if it no longer matters.',
    };
  if (head && task.status === 'done')
    return {
      yes: true,
      text: 'The work is finished. Read the result below, then accept it or send it back to be redone.',
    };
  if (task.status === 'assigned' && opts.auto === false)
    return {
      yes: true,
      text: 'No agent may start this on its own, because it costs money or trials. Press Run now if you want it done, or Cancel if you do not.',
    };
  if (head && opts.stuckSteps)
    return {
      yes: true,
      text: 'One of its steps is stuck. Ask AI for help, or open the steps below.',
    };
  if (task.status === 'closed' || task.status === 'cancelled')
    return { yes: false, text: 'Finished with. Nothing to do.' };
  return {
    yes: false,
    text: 'Nothing for you to do. The agents will carry on with it.',
  };
}

/** What pressing a button does, in a sentence. */
export function buttonHelp(action: Action, task: TaskLike, titles: Map<string, string>): string {
  const owner = who(task.owner, titles);
  switch (action) {
    case 'run':
      return task.kind === 'fix_code' || task.kind === 'code_feature'
        ? `Starts ${owner} now. It writes the change on a separate branch, which goes live only if you merge it.`
        : `Starts ${owner} on it now instead of waiting for its next scheduled run.`;
    case 'close':
      return 'You are happy with the result. The task is filed as done and nothing more runs.';
    case 'send_back':
      return `You are not happy with it. Its unfinished steps are dropped and ${owner} plans and runs it again.`;
    case 'retry':
      return 'Puts the task back in the queue so it is tried again.';
    case 'cancel':
      return 'Drops the task. Nothing more runs. You can retry it later.';
    case 'assist':
      return 'The AI reads what went wrong once, then either fixes the task and queues it again, or writes you what it needs.';
  }
}
