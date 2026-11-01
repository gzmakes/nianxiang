import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Collection;
import org.jetbrains.kotlin.cli.jvm.compiler.EnvironmentConfigFiles;
import org.jetbrains.kotlin.cli.jvm.compiler.KotlinCoreEnvironment;
import org.jetbrains.kotlin.config.CompilerConfiguration;
import org.jetbrains.kotlin.psi.KtFile;
import org.jetbrains.kotlin.psi.KtPsiFactory;
import org.jetbrains.kotlin.com.intellij.openapi.Disposable;
import org.jetbrains.kotlin.com.intellij.openapi.util.Disposer;
import org.jetbrains.kotlin.com.intellij.psi.PsiErrorElement;
import org.jetbrains.kotlin.com.intellij.psi.util.PsiTreeUtil;

/** Official Kotlin parser, without pretending unresolved Android APIs compiled. */
public final class KotlinSyntaxCheck {
    public static void main(String[] paths) throws Exception {
        Disposable disposable = Disposer.newDisposable();
        int errors = 0;
        try {
            KotlinCoreEnvironment environment = KotlinCoreEnvironment.createForProduction(disposable, new CompilerConfiguration(), EnvironmentConfigFiles.JVM_CONFIG_FILES);
            KtPsiFactory factory = new KtPsiFactory(environment.getProject(), false);
            for (String name : paths) {
                Path path = Path.of(name);
                KtFile file = factory.createFile(path.getFileName().toString(), Files.readString(path));
                Collection<PsiErrorElement> findings = PsiTreeUtil.collectElementsOfType(file, PsiErrorElement.class);
                for (PsiErrorElement finding : findings) {
                    int offset = finding.getTextOffset();
                    long line = file.getText().substring(0, Math.min(offset, file.getTextLength())).chars().filter(value -> value == '\n').count() + 1;
                    System.err.println(path + ":" + line + " " + finding.getErrorDescription());
                    errors++;
                }
            }
        } finally { Disposer.dispose(disposable); }
        System.out.println("KOTLIN_PARSER_ONLY: " + paths.length + " files, " + errors + " syntax errors; Android/Compose types are NOT resolved.");
        if (errors > 0) System.exit(1);
    }
}
