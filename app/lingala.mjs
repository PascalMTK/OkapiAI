// French synthesizers interpret this spelling. The original orthography stays visible.
const vowel = /^[aeɛioɔu]$/u;
const tones = { '\u0301': 1.18, '\u0302': 1.07, '\u030c': 1.02 };
const spelling = { e: 'é', ɛ: 'è', o: 'ô', ɔ: 'o', u: 'ou', ny: 'gn', ng: 'ng', ns: 'nss' };

export function lingalaSpeech(text) {
  const words = text.toLowerCase().normalize('NFD').match(/[\p{L}\p{M}]+|[.!?,;:]/gu) || [];
  return words.flatMap(word => {
    if (/^[.!?,;:]$/.test(word)) return [{ text: word, pitch: 1 }];
    const syllables = [];
    const letters = word.match(/mb|mp|nd|nt|ng|nk|nz|ns|ny|\p{L}\p{M}*/gu) || [];
    let onset = '';
    for (const letter of letters) {
      const [base, ...marks] = letter;
      if (vowel.test(base)) {
        let consonants = spelling[onset] || onset;
        if (onset.endsWith('g') && /[eɛi]/.test(base)) consonants += 'u';
        if (onset === 's' && syllables.length) consonants = 'ss';
        syllables.push({ text: consonants + (spelling[base] || base), pitch: tones[marks[0]] || 0.94 });
        onset = '';
      } else {
        onset += letter;
      }
    }
    if (!syllables.length) return [{ text: word, pitch: 1 }];
    syllables.at(-1).text += onset;
    return syllables;
  }).reduce((phrases, part) => {
    const previous = phrases.at(-1);
    if (previous && /^[.!?,;:]$/.test(part.text)) previous.text += part.text;
    else phrases.push(part);
    return phrases;
  }, []);
}
