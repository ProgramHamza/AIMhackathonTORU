import { SourceLink } from './SourceLink';
import { parseLinked } from '../lib/linkedText';

/** Renders text with only its marked key terms linked to their sources; long passages become markers. */
export function LinkedText({ text, sources, citedFor }) {
  return parseLinked(text).map((part, i) =>
    typeof part === 'string' ? (
      <span key={i}>{part}</span>
    ) : part.marker ? (
      <SourceLink key={i} source={sources[part.source]} citedFor={citedFor} marker>
        {part.marker}
      </SourceLink>
    ) : (
      <SourceLink key={i} source={sources[part.source]} citedFor={citedFor}>
        {part.term}
      </SourceLink>
    ),
  );
}
